"""The snapshot loader is the reproducible spine — pin its shape and the hero cast."""
from dealfinder.schema import Product
from dealfinder.snapshot import load_products, load_snapshot, load_snapshot_meta, to_products


def test_snapshot_loads_270_real_items():
    rows = load_snapshot()
    assert len(rows) == 270
    # flat real-listing shape (spec §2)
    r = rows[0]
    for key in ("id", "query", "category", "title", "brand", "price",
                "currency", "source", "marketplace", "url", "image_url",
                "deal_pct", "median_price_at_capture"):
        assert key in r


def test_meta_describes_the_corpus():
    meta = load_snapshot_meta()
    assert meta["domain"] == "consumer-electronics"
    assert meta["n_items"] == 270


def test_to_products_maps_to_schema():
    products = to_products(load_snapshot())
    assert len(products) == 270
    assert all(isinstance(p, Product) for p in products)
    p = products[0]
    assert p.marketplace in ("RapidAPI", "Apify")
    assert p.condition in ("new", "refurb", "used")


def test_hero_cast_is_present_at_the_expected_prices():
    # The recurring cast (spec §3) must be findable at the exact quoted prices.
    products = load_products()

    sony = next(p for p in products if "WH-1000XM5" in p.title and p.price == 162.97)
    anker = next(p for p in products if "Q20i" in p.title)
    bose = next(p for p in products if "QuietComfort 45" in p.title)

    assert sony.price == 162.97
    assert anker.price == 44.99
    assert bose.price == 46.0
