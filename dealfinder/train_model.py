"""Train the price model on the catalog, report accuracy, and surface deals.

Run:  python -m dealfinder.train_model
"""
from __future__ import annotations

import json
from pathlib import Path

from .deal import deal_score, is_deal
from .dealmodel import LinearModel, mae, r2, train_test_split
from .features import FEATURE_NAMES, feature_matrix
from .schema import Product

CATALOG = Path("data/sample/catalog.json")
DEAL_THRESHOLD = 0.15


def load_catalog(path: Path = CATALOG) -> list[Product]:
    return [Product.model_validate(r) for r in json.loads(path.read_text())]


def main() -> None:
    products = load_catalog()
    X = feature_matrix(products)
    y = [p.price for p in products]

    train_idx, test_idx = train_test_split(len(products), test_frac=0.25, seed=0)
    model = LinearModel().fit(X[train_idx], [y[i] for i in train_idx])

    pred_test = model.predict(X[test_idx])
    actual_test = [y[i] for i in test_idx]
    print(f"trained on {len(train_idx)} tents, tested on {len(test_idx)}")
    print(f"  MAE  = ${mae(actual_test, pred_test):.2f}")
    print(f"  R^2  = {r2(actual_test, pred_test):.3f}")

    print("\nlearned price drivers (intercept + per-feature $):")
    print(f"  intercept   {model.coef_[0]:+.1f}")
    for name, w in zip(FEATURE_NAMES, model.coef_[1:]):
        print(f"  {name:<11} {w:+.1f}")

    # Score the whole catalog against its predicted fair price.
    fair = model.predict(X)
    deals = [
        (p.id, p.price, fp, deal_score(p.price, fp))
        for p, fp in zip(products, fair)
        if is_deal(p.price, fp, DEAL_THRESHOLD)
    ]
    deals.sort(key=lambda d: d[3], reverse=True)
    print(f"\ndeals found (>= {int(DEAL_THRESHOLD * 100)}% under fair price): {len(deals)}")
    for pid, price, fp, score in deals:
        print(f"  {pid}: ${price:.0f} vs fair ${fp:.0f}  →  {score * 100:.0f}% off")


if __name__ == "__main__":
    main()
