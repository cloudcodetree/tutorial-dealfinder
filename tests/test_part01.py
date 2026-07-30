"""Part 1 reproducibility checks — pinned against the frozen electronics snapshot.

These assert the exact facts the Part 1 tutorial states. They pass only against
the committed `electronics-2026-07.json`; regenerate the snapshot and they will
(by design) drift.
"""
import statistics

from dealfinder.ingest import dedup_key, ingest
from dealfinder.schema import Product
from dealfinder.snapshot import load_snapshot, to_products


class _StaticSource:
    """A DealSource stub that just replays a fixed product list."""

    def __init__(self, products):
        self._products = products

    def products(self):
        return self._products


def test_snapshot_count():
    assert len(load_snapshot()) == 270


def test_brand_field_is_retailer_polluted():
    # 154 of 270 rows carry a retailer token in `brand` — the exact audit the
    # extraction lesson (Part 6) documents and runs.
    items = load_snapshot()
    retailers = ["Walmart", "Target", "Costco", "Macy", "Best Buy", "Amazon",
                 "mountainlifestyle", "kohl"]
    polluted = sum(
        1 for x in items
        if any(r.lower() in (x.get("brand") or "").lower() for r in retailers)
    )
    assert polluted == 154


def test_hero_query_median_is_pinned():
    ncb = [i for i in load_snapshot() if i["query"] == "noise cancelling headphones"]
    assert len(ncb) == 15
    prices = sorted(float(i["price"]) for i in ncb)
    assert abs(statistics.median(prices) - 162.97) < 0.01


def test_xm5_cross_retailer_offers_are_both_kept():
    # The Sony WH-1000XM5 appears at Costco ($162.97) and Macy's ($248): different
    # retailer brands + titles → distinct exact-match keys → BOTH kept (compare!).
    xm5 = [p for p in to_products(load_snapshot()) if "wh-1000xm5" in p.title.lower()]
    assert len(xm5) == 2
    assert len({dedup_key(p) for p in xm5}) == 2


def test_exact_duplicate_collapses_to_cheapest():
    # A genuine exact duplicate (same brand + title) DOES collapse, keeping the cheaper.
    a = Product(id="a", title="Anker Q20i", brand="Anker", category="audio",
                price=54.99, url="u", source="feed")
    b = Product(id="b", title="Anker Q20i", brand="Anker", category="audio",
                price=44.99, url="u", source="feed")
    out = ingest([_StaticSource([a, b])])
    assert len(out) == 1 and out[0].price == 44.99


def test_deal_pct_outliers_are_unsanitized():
    # Part 1 keeps the raw mess: extreme deal_pct values survive into the snapshot.
    dps = [float(i["deal_pct"]) for i in load_snapshot()]
    assert min(dps) < -3000
    assert max(dps) > 90
