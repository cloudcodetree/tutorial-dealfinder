"""Turn a messy free-text listing into schema-validated specs.

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
import re

from pydantic import BaseModel

from .features import BRAND_TIER


class ListingSpecs(BaseModel):
    brand: str | None = None
    capacity: int | None = None
    weight_kg: float | None = None
    season: int | None = None


def rule_extract(text: str) -> ListingSpecs:
    """Heuristic extraction — a deterministic stand-in for the LLM (offline)."""
    brand = next((b for b in BRAND_TIER if b.lower() in text.lower()), None)

    cap = re.search(r"(\d+)\s*-?\s*person|sleeps\s+(\d+)|\bUL(\d+)\b", text, re.I)
    capacity = int(next(g for g in cap.groups() if g)) if cap else None

    weight_kg = None
    if m := re.search(r"(\d+(?:\.\d+)?)\s*kg", text, re.I):
        weight_kg = float(m.group(1))
    elif m := re.search(r"(\d+(?:\.\d+)?)\s*g\b", text, re.I):
        weight_kg = round(float(m.group(1)) / 1000, 3)

    season = int(m.group(1)) if (m := re.search(r"(\d)\s*-?\s*season", text, re.I)) else None

    return ListingSpecs(brand=brand, capacity=capacity, weight_kg=weight_kg, season=season)


def build_prompt(text: str) -> str:
    """The extraction prompt — explicit schema, JSON-only, no guessing."""
    return (
        "Extract tent specs from the listing as JSON with keys "
        "brand (string|null), capacity (int|null), weight_kg (float|null), "
        "season (int|null). Use null if absent. Return ONLY the JSON.\n\n"
        f"Listing: {text}"
    )


def parse_llm_json(raw: str) -> ListingSpecs:
    """Validate an LLM's JSON text into the schema (raises if it doesn't fit)."""
    return ListingSpecs.model_validate(json.loads(raw))


def llm_extract(text: str, client=None, model: str = "gpt-4o-mini") -> ListingSpecs:
    """Production path: prompt an LLM at temperature 0 and validate the result.

    `client` is any OpenAI-compatible chat client. Without one we fall back to
    the deterministic extractor so the pipeline always runs.
    """
    if client is None:
        return rule_extract(text)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": build_prompt(text)}],
    )
    return parse_llm_json(resp.choices[0].message.content)
