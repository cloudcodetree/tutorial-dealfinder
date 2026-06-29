from datetime import date

from dealfinder.schema import PricePoint, Product


def test_product_requires_core_fields_and_defaults():
    p = Product(
        id="x1", title="Tent", brand="TrailLite", category="tents",
        price=189.0, url="https://ex/x1", source="dataset",
    )
    assert p.currency == "USD"
    assert p.specs == {}
    assert p.price_history == []


def test_price_history_typed():
    p = Product(
        id="x1", title="t", brand=None, category="c", price=1.0,
        url="u", source="dataset", price_history=[{"day": "2026-06-01", "price": 9.0}],
    )
    assert p.price_history[0] == PricePoint(day=date(2026, 6, 1), price=9.0)
