"""The license-aware shopper scorer (offline; no model, no network)."""
import pytest

from dealfinder import licensing, shop
from tests.conftest import row


def test_peer_fair_prices_flags_the_within_cluster_outlier(monkeypatch):
    # The category-agnostic fallback: an offer's fair price is the median of its
    # nearest semantic neighbors in the result set. With identical embeddings every
    # offer's peers are the others, so the cheap outlier's fair price is the median
    # of the rest — far above it. Mock embeddings → hermetic, no model needed.
    offers = [{"title": f"acoustic guitar {i}", "price": p}
              for i, p in enumerate([60.0, 65.0, 70.0, 75.0, 80.0])]
    offers.append({"title": "acoustic guitar cheap", "price": 8.0})
    monkeypatch.setattr(shop, "_embed_texts", lambda titles: [[1.0, 0.0] for _ in titles])
    pf = shop.peer_fair_prices(offers)
    assert pf[5] >= 60.0          # the $8 outlier's peer fair is the median of the rest


def test_score_offers_drops_rows_that_may_not_be_mixed():
    rows = [row("bestbuy-1", "Sony WH-1000XM5", 50.0, "BestBuy"), row("ebay-1", "Sony WH-1000XM5", 40.0, "eBay:Used")]
    assert [r["id"] for r in shop.score_offers(rows, median=60.0)] == ["bestbuy-1"]


def test_unrated_store_rows_stay_without_any_signal(monkeypatch):
    unrated = licensing.SourcePolicy("Unrated", verdicts=False, store=True, embed=False, comingle=True,
                                     max_age_s=60, launch=False, attribution=None)
    monkeypatch.setitem(licensing.POLICIES, "Unrated", unrated)
    r = shop.score_offers([row("u-1", "Thing", 5.0, "Unrated")], median=10.0)[0]
    assert all(r[k] is None for k in ("verdict", "fair", "residual_frac", "basis", "pct_under_median"))
    assert r["reason"] == "Not rated: this store's terms don't allow price ratings."


def test_regular_price_never_moves_a_signal(monkeypatch):
    monkeypatch.setattr(shop, "_embed_texts", lambda t: [[1.0, 0.0] for _ in t])
    base = [row(f"bestbuy-{i}", f"Guitar {i}", p, "BestBuy") for i, p in enumerate([60.0, 65.0, 70.0])]
    keys = ("verdict", "fair", "residual_frac", "pct_under_median", "reason")
    plain = shop.score_offers(base, median=65.0)
    inflated = shop.score_offers([{**r, "regular_price": 500.0} for r in base], median=65.0)
    assert [{k: r[k] for k in keys} for r in plain] == [{k: r[k] for k in keys} for r in inflated]
    assert not any(w in r["reason"].lower() for r in inflated for w in ("was", "regular"))


@pytest.mark.parametrize("title, sku, slug", [
    ("Sony WH-1000XM5 Wireless Noise Canceling Headphones - Black", "6505727",
     "sony-wh-1000xm5-wireless-noise-canceling-headphones-black-bestbuy-6505727"),
    ('Ünïcode / TV 65"', "1", "unicode-tv-65-bestbuy-1"),
    ("x", None, None)])
def test_offer_slug(title, sku, slug):
    assert shop.offer_slug(title, sku) == slug


def test_offer_slug_caps_the_title_part():
    s = shop.offer_slug("word " * 40, "9")
    assert len(s.removesuffix("-bestbuy-9")) <= 60 and not s.startswith("-")
