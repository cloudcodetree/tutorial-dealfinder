from dealfinder.sources import DatasetSource


def test_dataset_source_normalizes():
    items = list(DatasetSource("data/sample/products.json").products())
    p = next(i for i in items if i.id == "traillite-ul2")
    assert p.source == "dataset"
    assert p.brand == "TrailLite"
    assert p.price == 189.0
    assert p.specs["weight_kg"] == "1.1"
    assert p.price_history[-1].price == 189.0
