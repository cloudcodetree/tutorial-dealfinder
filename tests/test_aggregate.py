"""Aggregator logic is tested offline with stub sources (no network)."""
from dealfinder.aggregate import aggregate
from dealfinder.schema import Product


class _Stub:
    def __init__(self, name, products):
        self.name = name
        self._products = products

    def available(self):
        return True

    def search(self, query, limit=15):
        return self._products


def _p(pid, title, price, source):
    return Product(id=pid, title=title, brand="B", category="c", price=price, url="", source=source)


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
