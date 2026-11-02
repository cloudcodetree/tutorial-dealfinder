"""Plan 5 Task 7: Sentry with query scrubbing, JSON request logs with real cost, call-rate warnings."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dealfinder import observability
from dealfinder.observability import (LOG_FIELDS, CallRateGuard, add_llm_usage, cost_scope,
                                       scrub_breadcrumb, scrub_event)
from dealfinder.serve import app

client = TestClient(app)


@pytest.fixture
def stub_sources(monkeypatch):
    """/search and /search/stream with no network and no database."""
    from dealfinder import serve, shop
    monkeypatch.setattr(serve, "_DB", False)
    monkeypatch.setattr(shop, "aggregate", lambda q: {"results": [], "sources_live": []})
    monkeypatch.setattr(shop, "ebay_box", lambda q, limit=6: {"enabled": False, "note": "", "items": []})
    monkeypatch.setattr(serve, "enabled_sources", lambda names=None: [])


def _request_lines(out: str) -> list[dict]:
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [r for r in lines if r.get("message") == "request"]


def last_request_line(capsys) -> dict:
    return _request_lines(capsys.readouterr().out)[-1]


def test_request_log_has_no_query_text(capsys, stub_sources):
    client.get("/search", params={"q": "secret headphones 123"})
    out = capsys.readouterr().out
    rec = _request_lines(out)[-1]
    assert "secret" not in out and rec["route"] == "/search" and set(rec) == LOG_FIELDS


def test_request_log_has_no_client_ip(capsys, stub_sources):
    client.get("/search", params={"q": "tv"}, headers={"CF-Connecting-IP": "198.51.100.7"})
    assert "198.51.100.7" not in capsys.readouterr().out


def test_request_log_carries_latency_and_cost(capsys, stub_sources):
    client.get("/search", params={"q": "tv"})
    rec = last_request_line(capsys)
    assert rec["latency_ms"] >= 0 and set(rec["cost"]) >= {"usd", "llm_calls", "neurons", "source_calls"}


def test_request_log_uses_the_route_template(capsys):
    client.get("/lab/notes.txt")
    rec = last_request_line(capsys)
    assert rec["route"] == "/lab/{name}" and rec["status"] == 404


def test_check_logs_no_title_or_price(capsys):
    client.get("/check", params={"title": "Sony WH-1000XM5 secret", "price": 199})
    out = capsys.readouterr().out
    assert "secret" not in out and "199" not in out and _request_lines(out)[-1]["route"] == "/check"


def test_streaming_response_logs_once(capsys, stub_sources):
    with client.stream("GET", "/search/stream", params={"q": "tv"}) as r:
        b"".join(r.iter_bytes())
    lines = [r for r in _request_lines(capsys.readouterr().out) if r["route"] == "/search/stream"]
    assert len(lines) == 1 and lines[0]["status"] == 200


def test_llm_usage_comes_from_the_response():
    with cost_scope() as c:
        add_llm_usage("workers-ai", "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
                      {"prompt_tokens": 812, "completion_tokens": 96})
    assert (c.tokens_in, c.tokens_out, c.usd, c.cost_basis) == (812, 96, 0.0, "workers-ai-free")
    assert c.neurons == pytest.approx(812 * 4119 / 1e6 + 96 * 34868 / 1e6)


def test_missing_usage_is_null_not_guessed():
    with cost_scope() as c:
        add_llm_usage("workers-ai", "@cf/meta/llama-3.1-8b-instruct-fp8-fast", None)
    assert c.tokens_in is None and c.neurons is None and c.llm_calls == 1


def test_openrouter_cost_comes_from_its_response():
    with cost_scope() as c:
        add_llm_usage("openrouter", "some/model:free", {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0})
    assert (c.usd, c.cost_basis, c.neurons) == (0.0, "openrouter-reported", None)


def test_sentry_scrubs_query_string():
    ev = {"request": {"url": "https://x/search?q=secret", "query_string": "q=secret",
                      "headers": {"Authorization": "Bearer t", "Cookie": "a=b"}},
          "breadcrumbs": {"values": [{"data": {"url": "/search?q=secret"}}]}, "extra": {"q": "secret"}}
    out = json.dumps(scrub_event(ev, {}))
    assert "secret" not in out and "Bearer" not in out and "a=b" not in out


def test_sentry_scrubs_breadcrumbs_one_at_a_time():
    crumb = scrub_breadcrumb({"category": "httplib", "data": {"url": "https://x/check?title=secret&price=1"}}, {})
    assert "secret" not in json.dumps(crumb)


def test_init_sentry_is_a_no_op_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    called = []
    monkeypatch.setattr("sentry_sdk.init", lambda **k: called.append(k))
    observability.init_sentry()
    assert called == []


def test_init_sentry_never_sends_pii(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.us.sentry.io/0")
    called = []
    monkeypatch.setattr("sentry_sdk.init", lambda **k: called.append(k))
    observability.init_sentry()
    k = called[0]
    assert k["send_default_pii"] is False and k["before_send"] is scrub_event
    assert k["before_breadcrumb"] is scrub_breadcrumb and k["traces_sample_rate"] == 0.05


def test_call_rate_warning_fires_once(monkeypatch):
    sent = []
    monkeypatch.setattr("sentry_sdk.capture_message", lambda m, **k: sent.append(m))
    g = CallRateGuard(max_instances=1)
    g.add("resend", 80)
    g.add("resend", 5)
    assert sent == ["call-rate: resend at 80% of its daily cap"]


def test_call_rate_cap_is_shared_across_instances(monkeypatch):
    sent = []
    monkeypatch.setattr("sentry_sdk.capture_message", lambda m, **k: sent.append(m))
    g = CallRateGuard(max_instances=2)
    g.add("resend", 40)          # 80% of 100 / 2 instances
    assert sent == ["call-rate: resend at 80% of its daily cap"]


def test_request_cost_never_reads_the_static_price_table():
    assert "PRICES" not in Path(observability.__file__).read_text()


def test_uvicorn_access_log_is_off_in_the_image():
    # Uvicorn's own access line prints the full URL, query included. The JSON request
    # log replaces it.
    assert "--no-access-log" in Path("Dockerfile").read_text()


def test_sentry_never_sees_the_edge_secret_or_the_client_ip():
    ev = {"request": {"url": "https://x/check", "headers": {"X-DealFinder-Edge": "s3cret-edge",
                                                            "CF-Connecting-IP": "198.51.100.7",
                                                            "Referer": "https://deals/?q=secret"}}}
    out = json.dumps(scrub_event(ev, {}))
    assert "s3cret-edge" not in out and "198.51.100.7" not in out and "secret" not in out


def test_transactions_are_scrubbed_too(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.us.sentry.io/0")
    called = []
    monkeypatch.setattr("sentry_sdk.init", lambda **k: called.append(k))
    observability.init_sentry()
    assert called[0]["before_send_transaction"] is scrub_event


# ── security review follow-up: frame locals, outgoing HTTP, message text ─────
def test_sentry_collects_no_local_variables(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.us.sentry.io/0")
    called = []
    monkeypatch.setattr("sentry_sdk.init", lambda **k: called.append(k))
    observability.init_sentry()
    assert called[0]["include_local_variables"] is False
    denied = called[0]["event_scrubber"].denylist
    assert {"q", "query", "messages", "prompt", "key", "title"} <= set(denied)


def test_scrub_drops_stack_frame_variables():
    ev = {"exception": {"values": [{"type": "X", "value": "boom", "stacktrace": {"frames": [
        {"function": "chat", "vars": {"key": "sk-or-secret", "q": "secret tv"}}]}}]}}
    out = json.dumps(scrub_event(ev, {}))
    assert "sk-or-secret" not in out and "secret tv" not in out


def test_scrub_breadcrumb_drops_outgoing_query_and_fragment():
    crumb = {"category": "httplib", "data": {"url": "https://api.bestbuy.com/v1/products(search=tv)",
                                             "http.query": "apiKey=BBKEY123&format=json", "http.fragment": "f"}}
    out = json.dumps(scrub_breadcrumb(crumb, {}))
    assert "BBKEY123" not in out and "http.query" not in out


def test_scrub_strips_outgoing_urls_from_transaction_spans():
    ev = {"type": "transaction", "spans": [{
        "op": "http.client", "description": "GET https://api.bestbuy.com/v1/products?apiKey=BBKEY123",
        "data": {"url": "https://api.bestbuy.com/v1/products?apiKey=BBKEY123", "http.query": "apiKey=BBKEY123",
                 "url.query": "apiKey=BBKEY123"}}],
          "contexts": {"trace": {"data": {"url": "https://x/check?title=secret"}}}}
    out = json.dumps(scrub_event(ev, {}))
    assert "BBKEY123" not in out and "secret" not in out


def test_scrub_strips_queries_from_exception_and_log_text():
    ev = {"exception": {"values": [{"type": "HTTPError", "value": "GET https://x/check?title=secret failed"}]},
          "logentry": {"message": "fetch https://y/search?q=secret", "formatted": "fetch https://y/search?q=secret"},
          "message": "GET /check?title=secret"}
    assert "secret" not in json.dumps(scrub_event(ev, {}))
