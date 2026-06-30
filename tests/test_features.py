from dealfinder.features import FEATURE_NAMES, featurize
from dealfinder.schema import Product


def _tent(**specs):
    return Product(
        id="t1", title="Tent", brand="TrailLite", category="tents",
        price=199.0, url="http://x", source="dataset",
        specs={k: str(v) for k, v in specs.items()},
    )


def test_featurize_reads_specs_and_brand_tier():
    p = _tent(capacity=2, weight_kg=1.1, season=3)
    f = featurize(p)
    assert len(f) == len(FEATURE_NAMES)
    # capacity, weight_kg, season, brand_tier(TrailLite=3)
    assert f == [2.0, 1.1, 3.0, 3.0]


def test_featurize_defaults_for_missing():
    p = Product(id="t2", title="Mystery", brand=None, category="tents",
                price=100.0, url="http://x", source="dataset", specs={})
    f = featurize(p)
    assert f == [0.0, 0.0, 3.0, 1.0]  # unknown brand → tier 1, season defaults 3
