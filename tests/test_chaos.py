"""Chaos / graceful-degradation tests for the tiered aggregator (Part 36).

Offline and deterministic: every "source" here is an in-process stub, so these
run in CI with no network and no API keys. They pin the *resilience* behaviour
the tutorial claims:

  1. One source raising / timing out does not sink the search — the aggregator
     still returns the healthy sources' offers, and the circuit breaker benches
     the bad one so it isn't retried on the next search.
  2. With *every* live source down, the response is still well-formed: an empty
     result set with a valid envelope — never a 500 and never a crash.

These mirror the real code paths in dealfinder/aggregate.py (the same `run()` /
`_bench()` / dedup logic that `serve.py`'s `/search` calls), exercised through
the public `aggregate()` entry point.
"""
from __future__ import annotations

import httpx

from dealfinder import aggregate as agg
from dealfinder.aggregate import COOLDOWN_SECONDS, aggregate
from dealfinder.schema import Product


def _p(pid: str, title: str, price: float, source: str) -> Product:
    return Product(id=pid, title=title, brand="B", category="c", price=price, url="", source=source)


class _Healthy:
    """A well-behaved source that returns a fixed list of offers."""

    def __init__(self, name: str, products: list[Product], tier: int = 1) -> None:
        self.name = name
        self._products = products
        self.tier = tier
        self.calls = 0

    def available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 15) -> list[Product]:
        self.calls += 1
        return self._products


class _Exploding:
    """A source that always raises — models a 500 / connection reset."""

    def __init__(self, name: str, exc: Exception, tier: int = 1) -> None:
        self.name = name
        self._exc = exc
        self.tier = tier
        self.calls = 0

    def available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 15) -> list[Product]:
        self.calls += 1
        raise self._exc


def setup_function() -> None:
    # Isolate circuit-breaker state between tests (module-level _cooldown dict).
    agg._cooldown.clear()


# --------------------------------------------------------------------------- #
# 1. One bad source → still returns healthy results + benches the bad one
# --------------------------------------------------------------------------- #

def test_one_source_raising_does_not_break_search() -> None:
    bad = _Exploding("BAD", RuntimeError("boom 500"), tier=1)
    good = _Healthy("GOOD", [_p("g1", "Widget", 40, "GOOD"),
                             _p("g2", "Gizmo", 60, "GOOD")], tier=1)

    out = aggregate("widget", sources=[bad, good])

    assert out["count"] == 2                       # healthy source still served
    assert {r["source"] for r in out["results"]} == {"GOOD"}
    assert "GOOD" in out["sources_live"]
    assert "BAD" in out["throttled"]               # the breaker flagged it
    assert bad.calls == 1


def test_one_source_timing_out_is_benched_by_circuit_breaker() -> None:
    """A timeout is just an exception to the aggregator: it benches the source so
    the *next* search skips it entirely (no retry storm on a flaky source)."""
    timeout_exc = httpx.ReadTimeout("timed out", request=None)  # type: ignore[arg-type]
    bad = _Exploding("SLOW", timeout_exc, tier=1)
    good = _Healthy("GOOD", [_p("g1", "Widget", 40, "GOOD")], tier=1)

    first = aggregate("widget", sources=[bad, good])
    assert "SLOW" in first["throttled"] and bad.calls == 1

    # Second search within the cooldown window: the bad source is benched and
    # must NOT be called again — the healthy source still serves results.
    second = aggregate("widget", sources=[bad, good])
    assert bad.calls == 1                           # not retried while benched
    assert "SLOW" not in second["sources_live"]
    assert second["count"] == 1 and second["results"][0]["source"] == "GOOD"

    # The bench is a real cooldown, not a permanent ban.
    assert agg._cooldown["SLOW"] > 0.0
    assert COOLDOWN_SECONDS == 90.0


def test_healthy_lower_tier_absorbs_a_failed_same_tier_source() -> None:
    """Even when the failing source shares the cheapest tier, the aggregator
    keeps the offers from its healthy tier-mate rather than aborting the tier."""
    bad = _Exploding("BAD", ConnectionError("reset"), tier=1)
    good = _Healthy("GOOD", [_p("g1", "A", 10, "GOOD"), _p("g2", "B", 20, "GOOD")], tier=1)

    out = aggregate("x", sources=[bad, good])
    assert out["count"] == 2
    assert out["results"][0]["price"] == 10          # cheapest first, still ranked
    assert "BAD" in out["throttled"]


# --------------------------------------------------------------------------- #
# 2. ALL sources down → well-formed empty response, never a 500
# --------------------------------------------------------------------------- #

def test_all_sources_down_returns_well_formed_empty_envelope() -> None:
    sources = [
        _Exploding("A", RuntimeError("500"), tier=1),
        _Exploding("B", httpx.ConnectError("refused", request=None), tier=1),  # type: ignore[arg-type]
        _Exploding("C", TimeoutError("timeout"), tier=2),
    ]
    out = aggregate("anything", sources=sources)

    # Envelope is intact and typed exactly like the happy path — no exception,
    # no None, no 500. The frontend renders "No offers found" off this shape.
    assert out["query"] == "anything"
    assert out["results"] == []
    assert out["count"] == 0
    assert out["median_price"] == 0.0
    assert out["sources_live"] == []
    assert set(out["throttled"]) == {"A", "B", "C"}
    # Every failed source was benched by the breaker.
    for name in ("A", "B", "C"):
        assert name in agg._cooldown


def test_no_available_sources_returns_empty_envelope() -> None:
    """If nothing is even `available()` (e.g. all keyless sources sit out), the
    aggregator returns the same well-formed empty envelope — not an error."""

    class _Unavailable:
        name = "OFF"
        tier = 1

        def available(self) -> bool:
            return False

        def search(self, query: str, limit: int = 15) -> list[Product]:  # pragma: no cover
            raise AssertionError("must not be called when unavailable")

    out = aggregate("x", sources=[_Unavailable()])
    assert out["count"] == 0 and out["results"] == []
    assert out["sources_live"] == [] and out["throttled"] == []
