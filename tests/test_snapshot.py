"""The snapshot loader is the reproducible spine — pin its shape and the hero cast."""
import json
from pathlib import Path

from dealfinder.schema import Product
from dealfinder.snapshot import load_products, load_snapshot, load_snapshot_meta, to_products


def test_snapshot_loads_270_real_items():
    rows = load_snapshot()
    assert len(rows) == 270
    # flat real-listing shape (spec §2)
    r = rows[0]
    for key in ("id", "query", "category", "title", "brand", "price",
                "currency", "source", "marketplace", "url",
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


SNAP = Path(__file__).resolve().parent.parent / "data" / "snapshots" / "electronics-2026-07.json"


def test_snapshot_file_has_no_image_urls():
    assert "image_url" not in SNAP.read_text()


def test_snapshot_rows_and_products_carry_no_images():
    assert all("image_url" not in r for r in load_snapshot())
    assert all(p.image_url is None for p in load_products())


def test_snapshot_builder_never_writes_image_urls():
    assert "image_url" not in (SNAP.parent.parent / "build_snapshot.py").read_text()


def test_loader_drops_an_image_url_a_future_snapshot_carries(tmp_path):
    f = tmp_path / "electronics-2099-01.json"
    f.write_text(json.dumps({"meta": {}, "items": [{"id": "x", "title": "T", "category": "audio", "price": 1,
                                                    "url": "u", "image_url": "https://img/x.jpg"}]}))
    assert "image_url" not in load_snapshot(str(f))[0]
    assert to_products(load_snapshot(str(f)))[0].image_url is None


def test_strip_images_is_idempotent_and_touches_only_image_lines(tmp_path):
    import sys
    sys.path.insert(0, str(SNAP.parent.parent.parent / "scripts"))
    from strip_snapshot_images import strip_images
    f = tmp_path / "s.json"
    original = {"meta": {"n": 2}, "items": [{"id": "a", "image_url": "https://i/a", "price": 1},
                                            {"id": "b", "price": 2, "image_url": ""}]}
    f.write_text(json.dumps(original, indent=2))
    assert strip_images(f) == 2
    assert json.loads(f.read_text()) == {"meta": {"n": 2}, "items": [{"id": "a", "price": 1}, {"id": "b", "price": 2}]}
    assert strip_images(f) == 0
