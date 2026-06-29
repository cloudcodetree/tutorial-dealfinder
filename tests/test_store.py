from dealfinder.schema import Product
from dealfinder.store import load, save


def _p(id):
    return Product(id=id, title="Tent", brand="Acme", category="tents",
                   price=10.0, url="u", source="dataset")


def test_save_load_roundtrip(tmp_path):
    db = str(tmp_path / "d.sqlite")
    assert save([_p("a"), _p("b")], db) == 2
    got = {p.id for p in load(db)}
    assert got == {"a", "b"}
