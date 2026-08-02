"""Turn a messy free-text listing into schema-validated specs.

Real broad-electronics titles are retailer-polluted ("Walmart - COWIN SE7 …"),
so the interesting work is pulling the *true* manufacturer out of the title,
not trusting the raw ``brand`` field. This module extracts electronics-general
fields — brand, category, condition, model — into one typed schema.

Two paths, one schema:
  - rule_extract: deterministic regex heuristics — what the tests run, offline.
  - llm_extract:  the production path — an LLM prompted to return JSON that we
    validate into the SAME Pydantic schema (so a bad field is caught, not
    ingested). Gated behind an API client; the tutorial shows it, tests skip it.

ListingSpecs is the contract: structured output means "the model's text must
parse into this typed shape — or it's rejected."
"""
from __future__ import annotations

import json
import os
import re

from pydantic import BaseModel

from .features import CATEGORY_CODES, parse_condition, title_brand

# Category vocabulary — the 11 real snapshot categories (shared with features.py).
KNOWN_CATEGORIES: tuple[str, ...] = tuple(CATEGORY_CODES)

# Category keyword hints — map words in a title to a snapshot category. Longest /
# most-specific first so "gaming laptop" resolves before a bare "laptop".
_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    (r"head ?phones?|earbuds?|ear ?buds?|speaker|soundbar|sound bar|airpods", "audio"),
    (r"keyboard|mouse|webcam|mousepad|mouse pad", "peripherals"),
    (r"\bssd\b|hard drive|hdd|micro ?sd|memory card|flash drive", "storage"),
    (r"monitor|display|\d+k\b", "displays"),
    (r"laptop|desktop|chromebook|\bpc\b|mini pc", "computers"),
    (r"tablet|kindle|e-?reader|smartphone|\bphone\b", "mobile"),
    (r"watch|smartwatch|fitness (?:band|tracker)|\bband\b", "wearables"),
    (r"vacuum|security camera|smart (?:plug|bulb|home)|doorbell|thermostat", "smart-home"),
    (r"graphics card|\bgpu\b|\brtx\b|\bcpu\b|processor|motherboard|\bram\b", "components"),
    (r"hub|adapter|cable|charger|power bank|dock|case|mount", "accessories"),
)
_CATEGORY_PATTERNS = [(cat, re.compile(pat, re.I)) for pat, cat in _CATEGORY_HINTS]

# A model designation: an alnum token carrying at least one digit and one letter
# (e.g. "WH-1000XM5", "Q20i", "770NC"), optionally hyphenated. Purely numeric
# tokens (a capacity like "2TB") and plain words are excluded.
_MODEL_RE = re.compile(r"\b([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b")
# Measurement tokens ("13-inch", "2TB", "512GB", "4K") look alnum but describe a
# spec, not a model — exclude them so we don't mistake a size for a model number.
_MEASURE_RE = re.compile(
    r"^\d+(?:\.\d+)?-?(?:inch|in|tb|gb|mb|k|hz|mah|w|wh|mm|cm)$", re.I
)


class ListingSpecs(BaseModel):
    brand: str | None = None
    category: str | None = None
    condition: str = "new"
    model: str | None = None


def guess_category(text: str) -> str | None:
    """Classify a listing into one of the snapshot categories from its wording."""
    for cat, pat in _CATEGORY_PATTERNS:
        if pat.search(text):
            return cat
    return None


def guess_model(text: str) -> str | None:
    """Pull the model designation (alnum token with digits+letters) from a title.

    Skips measurement tokens ("13-inch", "2TB") so a spec isn't mistaken for a
    model; prefers a longer alnum code over a bare two-char one when both exist.
    """
    best: str | None = None
    for tok in _MODEL_RE.findall(text):
        if not (any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)):
            continue
        if _MEASURE_RE.match(tok):
            continue
        if best is None or len(tok) > len(best):
            best = tok
    return best


def rule_extract(text: str) -> ListingSpecs:
    """Heuristic extraction — a deterministic stand-in for the LLM (offline).

    Reuses the title-brand and condition parsers the price model already relies
    on (``features.py``), so the extractor and the model agree on the true brand.
    """
    return ListingSpecs(
        brand=title_brand(text),
        category=guess_category(text),
        condition=parse_condition(text),
        model=guess_model(text),
    )


def build_prompt(text: str) -> str:
    """The extraction prompt — explicit schema, JSON-only, no guessing."""
    return (
        "Extract electronics specs from the listing as JSON with keys "
        "brand (string|null, the true manufacturer — NOT the retailer), "
        "category (string|null), condition (\"new\"|\"refurb\"|\"used\"), "
        "model (string|null). Use null if absent. Return ONLY the JSON.\n\n"
        f"Listing: {text}"
    )


def parse_llm_json(raw: str) -> ListingSpecs:
    """Validate an LLM's JSON text into the schema (raises if it doesn't fit).

    Tolerates code fences / prose around the JSON by grabbing the first object."""
    m = re.search(r"\{.*\}", raw.strip(), re.S)
    return ListingSpecs.model_validate(json.loads(m.group(0) if m else raw))


def _adapter_extract(text: str, adapter_path: str) -> ListingSpecs:
    """Run extraction with a local fine-tuned model (the Part-10 QLoRA artifact).

    Loads the merged model directory saved by the Part-10 notebook. Heavy deps
    (transformers/torch) import lazily so the core install never pays for them.
    Raises on any failure — llm_extract catches and degrades down the chain.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer  # lazy: GPU/optional path

    tokenizer = AutoTokenizer.from_pretrained(adapter_path)
    model = AutoModelForCausalLM.from_pretrained(adapter_path, device_map="auto")
    msgs = [{"role": "user", "content": build_prompt(text)}]
    inputs = tokenizer.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
    out = model.generate(inputs, max_new_tokens=80, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    return parse_llm_json(tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True))


def llm_extract(text: str, client=None, adapter_path: str | None = None) -> ListingSpecs:
    """Extract via LLM, degrading gracefully to the deterministic extractor.

    Order: fine-tuned adapter (if adapter_path set) → explicit OpenAI-compatible
    `client` → OpenRouter (tiered models) → rule_extract. So the pipeline always
    returns something valid.
    """
    if adapter_path is not None:
        try:
            return _adapter_extract(text, adapter_path)
        except Exception:
            pass  # missing artifact / deps / GPU → fall through the chain

    if client is not None:
        resp = client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role": "user", "content": build_prompt(text)}],
        )
        return parse_llm_json(resp.choices[0].message.content)

    if os.getenv("OPENROUTER_API_KEY"):
        from .llm import chat
        try:
            raw = chat([{"role": "user", "content": build_prompt(text)}], temperature=0, json_mode=True)
            return parse_llm_json(raw)
        except Exception:
            pass  # every model throttled/unavailable → fall through

    return rule_extract(text)
