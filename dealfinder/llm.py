"""The LLM client: Cloudflare Workers AI first, OpenRouter for development only.

Workers AI is the production provider. Cloudflare says it "does not use Customer
Content processed by Workers AI to train AI models" and keeps no inputs or outputs
after the request (https://developers.cloudflare.com/workers-ai/platform/privacy/).
Past the free allocation it errors instead of billing, and every caller already
falls back to its deterministic path on any LLM error. OpenRouter's free models may
log prompts, so production refuses it.

OpenRouter (development):

Same anti-throttle idea as the sources: try a primary model, fall through to
fallbacks on rate-limit/unavailability (429/402/403/404), and let callers
degrade to a deterministic path if every model is unreachable. Configure the
tier with OPENROUTER_MODELS (comma-separated); the default tier is **free-only**
(every model is an OpenRouter `:free` endpoint) so the app costs nothing to run.
Point OPENROUTER_MODELS at a paid model if you want higher quality and are
willing to pay.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from . import observability, settings

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_WORKERS_AI = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
WORKERS_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
_SKIP = {402, 403, 404, 429, 502, 503}  # unavailable/throttled → try next model


def models() -> list[str]:
    env = os.getenv("OPENROUTER_MODELS")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    # Free-only tier: never bills the user. Ordered strong→resilient; the last
    # entry, openrouter/free, auto-routes to whatever free model is available.
    return [
        "google/gemma-4-31b-it:free",
        "openai/gpt-oss-20b:free",
        "openrouter/free",
    ]


def provider() -> str | None:
    """"workers-ai" when its account and token are set; "openrouter" when its key is set
    and this is not production; else None, and callers take their deterministic path."""
    if os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_AI_TOKEN"):
        return "workers-ai"
    if os.getenv("OPENROUTER_API_KEY") and not settings.is_production():
        return "openrouter"
    return None


def available() -> bool:
    return provider() is not None


def _workers_ai_chat(messages: list[dict], temperature: float) -> str:
    model = os.getenv("WORKERS_AI_MODEL", WORKERS_AI_MODEL)
    url = _WORKERS_AI.format(account=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=model)
    try:
        r = httpx.post(url, headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_AI_TOKEN']}"},
                       json={"messages": messages, "temperature": temperature}, timeout=60)
    except httpx.HTTPError as e:
        raise RuntimeError(f"workers-ai: {type(e).__name__}") from None
    if r.status_code == 404 or "no such model" in r.text.lower():
        import sentry_sdk
        sentry_sdk.capture_message(f"workers-ai model missing: {model}", level="error")
        raise RuntimeError(f"workers-ai model missing: {model}")
    if r.status_code != 200:
        raise RuntimeError(f"workers-ai: HTTP {r.status_code}")
    result = r.json().get("result") or {}
    observability.add_llm_usage("workers-ai", model, result.get("usage"))
    text = result.get("response")
    if not isinstance(text, str):
        raise RuntimeError("workers-ai: no response text")
    return text


def chat(messages: list[dict], temperature: float = 0, json_mode: bool = False,
         model_tier: list[str] | None = None) -> str:
    """One completion from the configured provider. Workers AI takes no response_format,
    so JSON callers parse the first JSON object out of the text (_first_json)."""
    which = provider()
    if which == "workers-ai":
        return _workers_ai_chat(messages, temperature)
    if which is None:
        raise RuntimeError("no LLM provider configured")
    key = os.environ["OPENROUTER_API_KEY"]
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
            body = r.json()
            observability.add_llm_usage("openrouter", model, body.get("usage"))
            return body["choices"][0]["message"]["content"]
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


if __name__ == "__main__":
    # python -m dealfinder.llm probe: one tiny Workers AI call. Prints only the shape
    # of the response (key names), never the text, so a run can confirm where the
    # answer and the usage live before anything relies on them.
    import sys

    if sys.argv[1:] != ["probe"] or provider() != "workers-ai":
        sys.exit("usage: CLOUDFLARE_ACCOUNT_ID=… CLOUDFLARE_AI_TOKEN=… python -m dealfinder.llm probe")
    model = os.getenv("WORKERS_AI_MODEL", WORKERS_AI_MODEL)
    r = httpx.post(_WORKERS_AI.format(account=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=model),
                   headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_AI_TOKEN']}"},
                   json={"messages": [{"role": "user", "content": "Say ok."}], "max_tokens": 5}, timeout=60)
    body = r.json()
    print(f"HTTP {r.status_code}; keys: {sorted(body)}; result keys: {sorted(body.get('result') or {})}")
