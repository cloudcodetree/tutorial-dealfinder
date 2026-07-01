"""Aggregator logic is tested offline with stub sources (no network)."""
from dealfinder import aggregate as agg
from dealfinder.aggregate import aggregate
from dealfinder.schema import Product


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
