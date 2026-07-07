"""Offline tests for the OpenRouter client + graceful degradation (HTTP mocked)."""
import httpx
import respx

from dealfinder import llm
from dealfinder.extract import llm_extract

OR = "https://openrouter.ai/api/v1/chat/completions"


def _msg(content):
    return {"choices": [{"message": {"content": content}}]}


@respx.mock
def test_chat_falls_through_tier_on_throttle(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    respx.post(OR).mock(side_effect=[
        httpx.Response(429, json={"error": "rate limited"}),   # primary throttled
        httpx.Response(200, json=_msg("ok")),                  # fallback answers
    ])
    assert llm.chat([{"role": "user", "content": "hi"}], model_tier=["a", "b"]) == "ok"


@respx.mock
def test_extract_products_parses_rendered_page(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    respx.post(OR).mock(return_value=httpx.Response(200, json=_msg(
        '{"products":[{"title":"Buds","price":9.99,"store":"X","url":"u"}]}')))
    out = llm.extract_products("page text with a buds listing", "buds")
    assert out and out[0]["price"] == 9.99


@respx.mock
def test_llm_extract_degrades_to_rule_when_all_models_fail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    respx.post(OR).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))
    # every model throttled → falls back to the deterministic extractor
    s = llm_extract("Sony WH-1000XM5 Wireless Headphones")
    assert s.brand == "Sony" and s.category == "audio" and s.model == "WH-1000XM5"
