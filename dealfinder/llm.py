"""OpenRouter LLM client with a model tier + graceful degradation.

Same anti-throttle idea as the sources: try a cheap primary model, fall through
to fallbacks on rate-limit/unavailability (429/402/403/404), and let callers
degrade to a deterministic path if every model is unreachable. Configure the
tier with OPENROUTER_MODELS (comma-separated); default = cheap paid → free.
"""
from __future__ import annotations

import json
import os
import re

import httpx

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_SKIP = {402, 403, 404, 429, 502, 503}  # unavailable/throttled → try next model


def models() -> list[str]:
    env = os.getenv("OPENROUTER_MODELS")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return ["deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct:free"]


def available() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def chat(messages: list[dict], temperature: float = 0, json_mode: bool = False,
         model_tier: list[str] | None = None) -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    last = "no models"
    for model in (model_tier or models()):
        body: dict = {"model": model, "temperature": temperature, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(_ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=90)
        except httpx.HTTPError as e:
            last = f"{model}: {e}"
            continue
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        last = f"{model}: HTTP {r.status_code}"
        if r.status_code in _SKIP:
            continue          # throttled / unavailable → next tier
        r.raise_for_status()
    raise RuntimeError(f"all models failed ({last})")


def _first_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw.strip(), re.S)
    return json.loads(m.group(0) if m else raw)


def extract_products(page_text: str, query: str, max_items: int = 15) -> list[dict]:
    """Pull purchasable products out of rendered page text (used by the browser tier)."""
    prompt = (
        'From the page text, extract purchasable products as JSON: '
        '{"products":[{"title":string,"price":number,"store":string,"url":string}]}. '
        f'Only items with a real numeric price relevant to "{query}". Text:\n{page_text[:6000]}'
    )
    data = _first_json(chat([{"role": "user", "content": prompt}], temperature=0, json_mode=True))
    return (data.get("products") or [])[:max_items]
