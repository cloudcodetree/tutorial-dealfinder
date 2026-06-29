from dealfinder.ingest import dedup_key, ingest
from dealfinder.schema import Product


class Fake:
    name = "fake"

    def __init__(self, products):
        self._p = products

    def products(self):
        return iter(self._p)


def _p(id, price, brand="Acme", title="Tent", source="fake"):
    return Product(id=id, title=title, brand=brand, category="tents",
                   price=price, url=f"https://ex/{id}", source=source)


def test_dedup_keeps_cheapest_across_sources():
    a = Fake([_p("a", 200, source="dataset")])
    b = Fake([_p("b", 180, source="api")])  # same brand+title, cheaper
    out = ingest([a, b])
    assert len(out) == 1
    assert out[0].price == 180.0


def test_distinct_products_kept():
    out = ingest([Fake([_p("a", 200, title="Tent"), _p("c", 50, title="Pad")])])
    assert {p.title for p in out} == {"Tent", "Pad"}


def test_dedup_key_normalizes_brand_title():
    assert dedup_key(_p("a", 1, brand="Acme", title="Tent")) == "acme|tent"
