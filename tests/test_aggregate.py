"""Aggregator logic is tested offline with stub sources (no network).

The semantic dedup pass is isolated the same way: an autouse fixture replaces
``dedup._embed`` with a deterministic fake (distinct titles → near-orthogonal
vectors; the semantic test injects explicit near-identical vectors), so the
suite never loads the embedding model.
"""
import hashlib

import numpy as np
import pytest

from dealfinder import aggregate as agg
from dealfinder import dedup
from dealfinder.aggregate import aggregate
from dealfinder.schema import Product


def _fake_vec(title: str) -> np.ndarray:
    seed = int(hashlib.sha256(title.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    v = rng.normal(size=384).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    """Distinct titles get independent random unit vectors (cosine ≈ 0 in 384-d),
    so exact-key behavior is unchanged and no model download happens in CI."""
    monkeypatch.setattr(dedup, "_embed", lambda titles: np.stack([_fake_vec(t) for t in titles]))


class _Stub:
    def __init__(self, name, products, tier=5, fail=False):
        self.name = name
        self._products = products
        self.tier = tier
        self.fail = fail
        self.calls = 0

    def available(self):
        return True

    def search(self, query, limit=15):
        self.calls += 1
        if self.fail:
            raise RuntimeError("rate limited")
        return self._products


def _p(pid, title, price, source):
    return Product(id=pid, title=title, brand="B", category="c", price=price, url="", source=source)


def setup_function():
    agg._cooldown.clear()  # isolate the circuit-breaker state between tests


def test_aggregate_dedups_and_ranks_by_price():
    a = _p("a", "Tent X", 200, "S1")          # duplicate of b (same brand|title)…
    b = _p("b", "Tent X", 150, "S2")          # …but cheaper, so it wins
    c = _p("c", "Other", 100, "S1")
    out = aggregate("x", sources=[_Stub("S1", [a, c]), _Stub("S2", [b])])

    ids = [r["id"] for r in out["results"]]
    assert "a" not in ids                      # deduped to the cheaper offer
    assert out["results"][0]["price"] == 100   # cheapest first
    assert set(out["sources_live"]) == {"S1", "S2"}
    assert out["results"][0]["deal_pct"] > 0   # below the median


def test_early_stop_skips_pricier_tier():
    tier1 = _Stub("T1", [_p(f"a{i}", f"Item {i}", 100 + i, "S1") for i in range(13)], tier=1)
    tier2 = _Stub("T2", [_p("z", "Bonus", 5, "S2")], tier=2)
    out = aggregate("x", sources=[tier1, tier2], target=12)
    assert tier1.calls == 1 and tier2.calls == 0     # enough from tier 1 → tier 2 never runs
    assert "T2" not in out["sources_live"]


def test_circuit_breaker_benches_a_throttled_source():
    bad = _Stub("BAD", [], tier=1, fail=True)
    good = _Stub("GOOD", [_p("g", "Good", 10, "S")], tier=2)

    out1 = aggregate("x", sources=[bad, good])
    assert "BAD" in out1["throttled"] and bad.calls == 1

    out2 = aggregate("x", sources=[bad, good])       # bad is benched now
    assert bad.calls == 1                            # not called again
    assert "GOOD" in out2["sources_live"]


def test_semantic_dedup_collapses_cross_retailer_pair(monkeypatch):
    """Different titles for the same product (distinct exact keys) merge into one
    cluster at cosine >= 0.90; the cheapest offer survives. The unrelated item
    keeps its own cluster."""
    xm5_a = _p("xa", "Sony WH-1000XM5 Wireless Industry Leading Noise Canceling Headphones", 248.00, "Macys")
    xm5_b = _p("xb", "Sony WH-1000XM5 Noise Cancelling Headphones - Black", 162.97, "Costco")
    cable = _p("c", "USB-C Charging Cable 6ft", 9.99, "Walmart")

    base = _fake_vec(cable.title)
    near = {xm5_a.title: _fake_vec("xm5"), xm5_b.title: _fake_vec("xm5") * 0.999 + _fake_vec("noise") * 0.02}
    monkeypatch.setattr(
        dedup, "_embed",
        lambda titles: np.stack([near.get(t, base if t == cable.title else _fake_vec(t)) for t in titles]),
    )

    out = aggregate("x", sources=[_Stub("S1", [xm5_a, cable]), _Stub("S2", [xm5_b])])
    ids = {r["id"] for r in out["results"]}
    assert ids == {"xb", "c"}                       # XM5 pair collapsed, cheaper Costco offer won
    prices = {r["id"]: r["price"] for r in out["results"]}
    assert prices["xb"] == 162.97


def test_semantic_dedup_keeps_distinct_products_apart():
    """Near-orthogonal fake vectors (distinct titles) must never merge."""
    a = _p("a", "Sony WH-1000XM5 Headphones", 162.97, "S1")
    b = _p("b", "Samsung 27in 4K Monitor", 299.99, "S1")
    out = aggregate("x", sources=[_Stub("S1", [a, b])])
    assert {r["id"] for r in out["results"]} == {"a", "b"}
