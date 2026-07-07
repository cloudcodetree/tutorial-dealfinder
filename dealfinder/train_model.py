"""Train the price model on the frozen snapshot and surface the two-signal deals.

Run:  python -m dealfinder.train_model

This is the from-scratch linear baseline over the broad-electronics features
(category, title-extracted brand tier, condition). On heterogeneous data those
three hand-features leave most price variance unexplained — that failure is the
whole motivation for the §4 upgrade. Gradient boosting on categorical + title
embeddings is the Part-17 replacement for ``LinearModel`` here; the snapshot,
features, and two-signal score all stay the same so only the model swaps out.
"""
from __future__ import annotations

from .dealmodel import LinearModel, mae, r2, train_test_split
from .dealscore import verdict
from .features import FEATURE_NAMES, feature_matrix
from .snapshot import load_products

# The recurring hero query. Its cross-source median at capture (spec §3).
ANCHOR_QUERY = "noise cancelling headphones"
ANCHOR_MEDIAN = 162.97


def fit_price_model(products) -> LinearModel:
    """Fit the linear baseline on a (comparable) set of products."""
    X = feature_matrix(products)
    y = [p.price for p in products]
    return LinearModel().fit(X, y)


def main() -> None:
    products = load_products()

    # Report accuracy on the full heterogeneous corpus — this is deliberately
    # weak; the failure motivates the §4 upgrade (gradient boosting + embeddings).
    X = feature_matrix(products)
    y = [p.price for p in products]
    train_idx, test_idx = train_test_split(len(products), test_frac=0.25, seed=0)
    model = LinearModel().fit(X[train_idx], [y[i] for i in train_idx])
    pred_test = model.predict(X[test_idx])
    actual_test = [y[i] for i in test_idx]
    print(f"trained on {len(train_idx)} listings, tested on {len(test_idx)}")
    print(f"  MAE  = ${mae(actual_test, pred_test):.2f}")
    print(f"  R^2  = {r2(actual_test, pred_test):.3f}   (broad data → weak; see §4/Part 17)")

    print("\nlearned price drivers (intercept + per-feature $):")
    print(f"  intercept      {model.coef_[0]:+.1f}")
    for name, w in zip(FEATURE_NAMES, model.coef_[1:]):
        print(f"  {name:<14} {w:+.1f}")

    # Two-signal scoring on the anchor query. Fit fair prices within the
    # comparable audio category so brand tier drives the fair-price estimate,
    # then blend with the anchor query's live median.
    audio = [p for p in products if p.category == "audio"]
    audio_model = fit_price_model(audio)
    fair = audio_model.predict(feature_matrix(audio))
    print(f'\nverdicts on "{ANCHOR_QUERY}" (median ${ANCHOR_MEDIAN:.2f}):')
    for p, fp in zip(audio, fair):
        v = verdict(p.price, ANCHOR_MEDIAN, float(fp))
        if v.label in ("deal", "suspicious"):
            print(f"  [{v.label:<10}] ${p.price:<7.2f} {p.title[:46]:<46} — {v.reason}")


if __name__ == "__main__":
    main()
