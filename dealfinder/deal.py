"""Turn a price prediction into a deal verdict.

The model predicts a *fair* price from a product's features. A good deal is
simply a real price that sits meaningfully *below* that fair price — the gap,
as a fraction, is the deal score.
"""
from __future__ import annotations


def deal_score(actual: float, predicted: float) -> float:
    """Fraction below the predicted fair price. Positive = underpriced = a deal."""
    return (predicted - actual) / predicted


def is_deal(actual: float, predicted: float, threshold: float = 0.10) -> bool:
    """True when the price is at least `threshold` (default 10%) under fair value."""
    return deal_score(actual, predicted) >= threshold
