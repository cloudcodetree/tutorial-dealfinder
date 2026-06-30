"""Turn a Product into the numeric feature vector the price model learns from.

Feature engineering is where domain knowledge enters the model: we pick the
fields that plausibly drive a tent's price (size, weight, season rating, brand
tier) and express them as numbers. Everything the model knows, it knows through
these four columns.
"""
from __future__ import annotations

from .schema import Product

FEATURE_NAMES = ["capacity", "weight_kg", "season", "brand_tier"]

# A hand-mapped brand → tier. In production you'd learn this; here it's explicit
# so the feature is legible (premium brands command higher prices).
BRAND_TIER = {
    "TrailLite": 3, "SummitPro": 3,
    "BasecampCo": 2, "RidgeRunner": 2,
    "ValueOutdoors": 1, "BudgetTrail": 1,
}


def featurize(p: Product) -> list[float]:
    s = p.specs
    return [
        float(s.get("capacity", 0)),
        float(s.get("weight_kg", 0)),
        float(s.get("season", 3)),
        float(BRAND_TIER.get(p.brand or "", 1)),
    ]


def feature_matrix(products: list[Product]):
    import numpy as np

    return np.array([featurize(p) for p in products], dtype=float)
