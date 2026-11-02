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


# ── Workers AI (Plan 5 Task 8) ───────────────────────────────────────────────
import pytest  # noqa: E402

MODEL_URL = "https://api.cloudflare.com/client/v4/accounts/acct/ai/run/@cf/meta/llama-3.1-8b-instruct-fp8-fast"


@pytest.fixture
def cf_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "cf_ai")


@respx.mock
def test_workers_ai_chat_calls_the_pinned_model(cf_env):
    route = respx.post(MODEL_URL).mock(return_value=httpx.Response(200, json={
        "success": True, "result": {"response": "Best value: X at $10.00",
                                    "usage": {"prompt_tokens": 9, "completion_tokens": 7}}}))
    assert llm.chat([{"role": "user", "content": "hi"}]).startswith("Best value")
    assert route.calls[0].request.headers["Authorization"] == "Bearer cf_ai"


@respx.mock
def test_workers_ai_usage_reaches_the_request_cost(cf_env):
    from dealfinder.observability import cost_scope
    respx.post(MODEL_URL).mock(return_value=httpx.Response(200, json={
        "success": True, "result": {"response": "ok", "usage": {"prompt_tokens": 9, "completion_tokens": 7}}}))
    with cost_scope() as c:
        llm.chat([{"role": "user", "content": "hi"}])
    assert (c.llm_calls, c.tokens_in, c.tokens_out, c.cost_basis) == (1, 9, 7, "workers-ai-free")


@respx.mock
def test_workers_ai_missing_model_alerts_and_raises(cf_env, monkeypatch):
    sent = []
    monkeypatch.setattr("sentry_sdk.capture_message", lambda m, **k: sent.append((m, k.get("level"))))
    respx.post(MODEL_URL).mock(return_value=httpx.Response(404, json={"success": False, "errors": [{"message": "No such model"}]}))
    with pytest.raises(RuntimeError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert sent == [("workers-ai model missing: @cf/meta/llama-3.1-8b-instruct-fp8-fast", "error")]


def test_provider_prefers_workers_ai(cf_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert llm.provider() == "workers-ai" and llm.available() is True


def test_openrouter_still_works_outside_production(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert llm.provider() == "openrouter"


def test_openrouter_refused_in_production(monkeypatch):
    monkeypatch.setenv("DEALFINDER_ENV", "production")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    monkeypatch.delenv("CLOUDFLARE_AI_TOKEN", raising=False)
    assert llm.available() is False and llm.provider() is None


def test_no_keys_means_no_provider():
    assert llm.provider() is None and llm.available() is False
