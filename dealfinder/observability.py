"""Production telemetry that never carries what a shopper typed.

- **Sentry.** Errors reach Sentry only when `SENTRY_DSN` is set. Every event, transaction
  and breadcrumb is scrubbed before it leaves: no query string, cookies, body,
  `Authorization`, edge secret or client IP.
- **Request log.** One JSON line per request on stdout, keyed by the route template
  (`/search`, `/watchlist/{offer_id}`), never the URL. No query text, user id or IP.
- **Cost.** Each request's real LLM usage, read from the provider's own response. Nothing
  is estimated: a response without `usage` leaves tokens and neurons null. Workers AI is
  free, so `usd` is 0.0 and its neurons are counted against the daily allocation.
- **Call-rate guard.** Per-instance daily counts against the free caps, and one Sentry
  warning per key per UTC day at 80%, which Sentry emails to the owner.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterator

LOG_FIELDS = {"severity", "message", "route", "method", "status", "latency_ms", "cache", "cost", "revision"}

# Cloudflare's published Workers AI rate per model, in neurons per million input and
# output tokens: https://developers.cloudflare.com/workers-ai/platform/pricing/
WORKERS_AI_NEURONS_PER_M = {"@cf/meta/llama-3.1-8b-instruct-fp8-fast": (4119, 34868)}

# Free daily allowances: Best Buy's API limit, Workers AI's 10,000 neurons (shared with
# cloudcodetree.com), Resend Free's 100 emails.
DAILY_CAPS = {"BestBuy": 50_000, "workers-ai-neurons": 10_000, "resend": 100}

# Headers that identify a person or carry a secret. They never reach Sentry.
_SECRET_HEADERS = {"authorization", "cookie", "x-dealfinder-edge", "cf-connecting-ip",
                   "x-forwarded-for", "x-real-ip", "true-client-ip", "referer"}
_QUERY = re.compile(r"\?\S*")
# Keys whose values never leave the process: the sentry_sdk scrubber blanks them
# anywhere in an event (request, extra, contexts), on top of its own default list.
_DENY_KEYS = ["q", "query", "title", "messages", "prompt", "key", "api_key", "apikey", "token"]
# Span and breadcrumb data keys that hold an outgoing request's query or fragment.
# Best Buy's API key travels in its query string.
_HTTP_QUERY_KEYS = ("http.query", "http.fragment", "url.query", "url.fragment")


# ── cost ────────────────────────────────────────────────────────────────────
@dataclass
class Cost:
    usd: float | None = 0.0
    llm_calls: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    neurons: float | None = None
    source_calls: dict[str, int] = field(default_factory=dict)
    cost_basis: str | None = None


_COST: contextvars.ContextVar[Cost | None] = contextvars.ContextVar("dealfinder_cost", default=None)


@contextmanager
def cost_scope() -> Iterator[Cost]:
    """Collect one request's cost. Calls outside a scope are counted nowhere."""
    cost = Cost()
    token = _COST.set(cost)
    try:
        yield cost
    finally:
        _COST.reset(token)


def _plus(total, n):
    return n if total is None else total + n


def add_llm_usage(provider: str, model: str, usage: dict | None) -> None:
    """Record one LLM call from the provider's own `usage` block."""
    cost = _COST.get()
    neurons = None
    if usage:
        tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
        rate = WORKERS_AI_NEURONS_PER_M.get(model) if provider == "workers-ai" else None
        if rate and tin is not None and tout is not None:
            neurons = tin * rate[0] / 1e6 + tout * rate[1] / 1e6
            GUARD.add("workers-ai-neurons", neurons)
    if cost is None:
        return
    cost.llm_calls += 1
    if provider == "workers-ai":
        cost.cost_basis = "workers-ai-free"
    elif provider == "openrouter":
        cost.cost_basis = "openrouter-reported"
    if not usage:
        return
    if usage.get("prompt_tokens") is not None:
        cost.tokens_in = _plus(cost.tokens_in, usage["prompt_tokens"])
    if usage.get("completion_tokens") is not None:
        cost.tokens_out = _plus(cost.tokens_out, usage["completion_tokens"])
    if neurons is not None:
        cost.neurons = _plus(cost.neurons, neurons)
    if provider == "openrouter":
        reported = usage.get("cost")
        cost.usd = None if reported is None or cost.usd is None else cost.usd + reported


def add_source_call(source: str) -> None:
    """Record one call to a store source. Call it on the request's thread, not inside a pool."""
    GUARD.add(source)
    cost = _COST.get()
    if cost is not None:
        cost.source_calls[source] = cost.source_calls.get(source, 0) + 1


# ── call-rate guard ─────────────────────────────────────────────────────────
class CallRateGuard:
    """Per-instance daily counts. Each instance gets cap / max_instances, so the
    service as a whole stays inside the free allowance."""

    def __init__(self, max_instances: int | None = None,
                 today: Callable[[], object] = lambda: datetime.now(timezone.utc).date()):
        self.max_instances = max_instances or int(os.getenv("DEALFINDER_MAX_INSTANCES", "2"))
        self._today = today
        self._day = None
        self._counts: dict[str, float] = {}
        self._warned: set[str] = set()
        self._lock = threading.Lock()

    def add(self, key: str, n: float = 1) -> None:
        cap = DAILY_CAPS.get(key)
        if cap is None:
            return
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._counts, self._warned = day, {}, set()
            self._counts[key] = self._counts.get(key, 0) + n
            warn = self._counts[key] >= 0.8 * cap / self.max_instances and key not in self._warned
            if warn:
                self._warned.add(key)
        if warn:
            import sentry_sdk
            sentry_sdk.capture_message(f"call-rate: {key} at 80% of its daily cap", level="warning")


GUARD = CallRateGuard()


# ── Sentry ──────────────────────────────────────────────────────────────────
def _strip(url):
    return url.split("?", 1)[0].split("#", 1)[0] if isinstance(url, str) else url


def _scrub_data(data) -> None:
    if not isinstance(data, dict):
        return
    for key in _HTTP_QUERY_KEYS:
        data.pop(key, None)
    for key in ("url", "from", "to", "http.url", "url.full"):
        if key in data:
            data[key] = _strip(data[key])


def _scrub_text(value):
    return _QUERY.sub("", value) if isinstance(value, str) else value


def scrub_breadcrumb(crumb: dict, hint: dict) -> dict:
    _scrub_data(crumb.get("data"))
    if "message" in crumb:
        crumb["message"] = _scrub_text(crumb["message"])
    return crumb


def scrub_event(event: dict, hint: dict) -> dict:
    req = event.get("request")
    if isinstance(req, dict):
        for key in ("query_string", "cookies", "data", "env"):
            req.pop(key, None)
        if "url" in req:
            req["url"] = _strip(req["url"])
        headers = req.get("headers")
        if isinstance(headers, dict):
            for name in [h for h in headers if h.lower() in _SECRET_HEADERS]:
                headers.pop(name)
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for crumb in values if isinstance(values, list) else []:
        scrub_breadcrumb(crumb, {})
    extra = event.get("extra")
    if isinstance(extra, dict):
        for key in ("q", "query"):
            extra.pop(key, None)
    # Exceptions: their message text, and every frame's local variables.
    exc = event.get("exception")
    for value in (exc.get("values") if isinstance(exc, dict) else None) or []:
        value["value"] = _scrub_text(value.get("value"))
        for frame in ((value.get("stacktrace") or {}).get("frames") or []):
            frame.pop("vars", None)
    if "message" in event:
        event["message"] = _scrub_text(event["message"])
    log = event.get("logentry")
    if isinstance(log, dict):
        for key in ("message", "formatted"):
            log[key] = _scrub_text(log.get(key))
    # Transactions: every span's outgoing URL and description, and the trace context.
    for span in event.get("spans") or []:
        if isinstance(span, dict):
            span["description"] = _scrub_text(span.get("description"))
            _scrub_data(span.get("data"))
    trace = (event.get("contexts") or {}).get("trace")
    if isinstance(trace, dict):
        _scrub_data(trace.get("data"))
    return event


def init_sentry() -> None:
    """Start Sentry when SENTRY_DSN is set. Call it before the FastAPI app is created."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=0.05,
                    # Frame locals hold the query, the prompt and API keys. None are collected.
                    include_local_variables=False,
                    event_scrubber=EventScrubber(denylist=DEFAULT_DENYLIST + _DENY_KEYS, recursive=True),
                    environment=os.getenv("DEALFINDER_ENV", "development"),
                    release=os.getenv("K_REVISION"),
                    before_send=scrub_event, before_send_transaction=scrub_event,
                    before_breadcrumb=scrub_breadcrumb)


# ── request log ─────────────────────────────────────────────────────────────
def _emit(scope, status: int, started: float, cache: str | None, cost: Cost) -> None:
    route = getattr(scope.get("route"), "path", None) or "unmatched"
    record = {"severity": "ERROR" if status >= 500 else "INFO", "message": "request", "route": route,
              "method": scope.get("method"), "status": status,
              "latency_ms": round((time.perf_counter() - started) * 1000, 1), "cache": cache,
              "cost": asdict(cost), "revision": os.getenv("K_REVISION")}
    # sys.stdout at emit time, so Cloud Run's log agent and pytest's capsys both see it.
    print(json.dumps(record, separators=(",", ":")), file=sys.stdout, flush=True)


class RequestLogMiddleware:
    """Pure ASGI, so a streaming response logs once, when it finishes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        seen = {"status": 500, "cache": None}

        async def capture(message):
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"x-dealfinder-cache":
                        seen["cache"] = value.decode("latin-1")
            await send(message)

        with cost_scope() as cost:
            try:
                await self.app(scope, receive, capture)
            finally:
                _emit(scope, seen["status"], started, seen["cache"], cost)
