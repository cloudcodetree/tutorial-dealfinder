"""The license-aware shopper scorer (offline; no model, no network)."""
import pytest

from dealfinder import licensing, shop
from tests.conftest import row


@pytest.fixture(autouse=True)
def _fresh_ebay_cache():
    shop._ebay_cache.clear()
    yield
    shop._ebay_cache.clear()


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


def test_ebay_box_hidden_without_keys():
    assert shop.ebay_box("x") == {"enabled": False, "note": "Listings from eBay. Not compared or rated.", "items": []}


def test_ebay_box_hides_sandbox_data(monkeypatch):
    monkeypatch.setenv("EBAY_APP_ID", "x-SBX-y")
    monkeypatch.setenv("EBAY_CERT_ID", "c")
    assert shop.ebay_box("x")["enabled"] is False


class _FakeEbay:
    """Production-looking eBay client that records searches."""

    def __init__(self, calls, items=()):
        self.calls, self.items = calls, list(items)

    def available(self):
        return True

    def is_sandbox(self):
        return False

    def search(self, query, limit=15):
        self.calls.append(query)
        return self.items


def test_ebay_box_caches_at_most_15_minutes(monkeypatch):
    calls = []
    monkeypatch.setattr(shop, "EBAY", _FakeEbay(calls))
    start = shop._now()
    shop.ebay_box("TV")
    shop.ebay_box(" tv ")
    assert len(calls) == 1
    monkeypatch.setattr(shop, "_now", lambda: start + 901)
    shop.ebay_box("tv")
    assert len(calls) == 2


def test_ebay_box_keeps_ebays_order_and_shape(monkeypatch):
    from dealfinder.schema import Product
    items = [Product(id=f"ebay-{i}", title=f"Item {i}", brand=None, category="product", price=p,
                     url=f"https://ebay/{i}", source="eBay:Used", image_url=None) for i, p in enumerate([30.0, 10.0, 20.0])]
    monkeypatch.setattr(shop, "EBAY", _FakeEbay([], items))
    box = shop.ebay_box("x", limit=2)
    assert box["enabled"] is True and [i["id"] for i in box["items"]] == ["ebay-0", "ebay-1"]
    assert box["items"][0] == {"id": "ebay-0", "title": "Item 0", "price": 30.0, "currency": "USD",
                               "url": "https://ebay/0", "condition": "Used", "image_url": None}


def test_ebay_box_survives_an_ebay_error(monkeypatch):
    fake = _FakeEbay([])
    fake.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("eBay down"))
    monkeypatch.setattr(shop, "EBAY", fake)
    assert shop.ebay_box("x")["items"] == []


@pytest.mark.parametrize("value", ["Live ", "verdicts", "on", ""])
def test_unknown_mode_fails_closed(monkeypatch, value):
    monkeypatch.setenv("DEALFINDER_VERDICT_MODE", value)
    assert shop.verdict_mode() == "check"


def test_unset_mode_is_live(monkeypatch):
    monkeypatch.delenv("DEALFINDER_VERDICT_MODE", raising=False)
    assert shop.verdict_mode() == "live"


@pytest.mark.parametrize("price, verdict", [(25.0, "suspicious"), (30.0, "suspicious"), (80.0, "deal"), (85.0, "deal"),
                                            (90.0, "fair"), (114.0, "fair"), (115.0, "overpriced"), (120.0, "overpriced")])
def test_check_rule(monkeypatch, price, verdict):
    monkeypatch.setattr(shop, "_fair_for", lambda t: ("audio", 100.0))
    assert shop.check_deal("Sony WH-1000XM5", price)["verdict"] == verdict


def test_check_reason_copy_and_unknown_category(monkeypatch):
    monkeypatch.setattr(shop, "_fair_for", lambda t: ("audio", 100.0))
    assert shop.check_deal("Sony WH-1000XM5", 80.0)["reason"] == "20% below our fair price for this model (~$100)."
    assert shop.check_deal("Sony WH-1000XM5", 25.0)["reason"] == (
        "75% below our fair price for this model (~$100). That is too far below to be real. "
        "It may be used, an accessory, or a mislisting.")
    assert shop.check_deal("Sony WH-1000XM5", 120.0)["reason"] == "20% above our fair price for this model (~$100)."
    assert shop.check_deal("Sony WH-1000XM5", 100.0)["reason"] == "Within 15% of our fair price for this model (~$100)."
    assert shop.check_deal("Sony WH-1000XM5", 80.0)["basis"] == "model"
    monkeypatch.setattr(shop, "_fair_for", lambda t: (None, None))
    r = shop.check_deal("Mystery widget", 10.0)
    assert (r["verdict"], r["basis"], r["reason"]) == (None, None, "We can't estimate a fair price for this kind of product yet.")


def test_check_on_a_real_title(monkeypatch):
    # Pinned from a real run of the snapshot model (2026-10-27):
    # check_deal('Sony WH-1000XM5 Wireless Noise Canceling Headphones', 199.0)
    monkeypatch.delenv("DEALFINDER_VERDICT_MODE", raising=False)
    r = shop.check_deal("Sony WH-1000XM5 Wireless Noise Canceling Headphones", 199.0)
    assert (r["category"], r["fair"], r["verdict"]) == ("audio", 285.15, "deal")


def test_check_finds_the_category_from_a_bare_model_name(monkeypatch):
    # Shoppers type the model, not the product type. The category comes from the
    # snapshot listing that shares the title's words when the wording alone says nothing.
    monkeypatch.delenv("DEALFINDER_VERDICT_MODE", raising=False)
    r = shop.check_deal("Sony WH-1000XM5", 199.0)
    assert r["category"] == "audio" and r["verdict"] is not None and r["basis"] == "model"


def test_check_does_not_guess_from_a_weak_match():
    assert shop._fair_for("Mystery widget 3000") == (None, None)
