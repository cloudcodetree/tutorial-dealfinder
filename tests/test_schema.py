from datetime import date

from dealfinder.schema import PricePoint, Product


def test_product_requires_core_fields_and_defaults():
    p = Product(
        id="x1", title="Sony WH-1000XM5 Wireless Headphones", brand="costco.com",
        category="audio", price=162.97, url="https://ex/x1", source="snapshot",
    )
    assert p.currency == "USD"
    assert p.specs == {}
    assert p.price_history == []
    # broad-electronics defaults are backward-compatible
    assert p.condition == "new"
    assert p.marketplace is None


def test_new_electronics_fields_round_trip():
    p = Product(
        id="x2", title="Bose QuietComfort 45", brand="mountainlifestyle.ca",
        category="audio", price=46.0, url="https://ex/x2", source="snapshot",
        marketplace="RapidAPI", condition="refurb",
    )
    assert p.marketplace == "RapidAPI"
    assert p.condition == "refurb"


def test_price_history_typed():
    p = Product(
        id="x1", title="t", brand=None, category="c", price=1.0,
        url="u", source="snapshot", price_history=[{"day": "2026-07-01", "price": 9.0}],
    )
    assert p.price_history[0] == PricePoint(day=date(2026, 7, 1), price=9.0)
