"""The two-signal deal score (spec §4): cross-source median + model residual.

The naive median signal is fast and model-free but *fooled* on broad electronics:
a $46 Bose QuietComfort 45 reads "72% under the $162.97 median" and looks like the
deal of the year — but a $329-MSRP flagship at $46 is refurb/mislisted, not a
bargain. The median alone rewards exactly this false positive.

So we blend two signals:

1. ``median_signal`` — % below the same-query cross-source median (from
   ``aggregate.py``). Primary, but noisy.
2. ``residual_signal`` — a *guard*. A price model predicts a fair price from the
   product's real features (category, title-extracted brand tier, condition). If
   the market median says "steal" but the model's fair price is far above the
   actual, we don't trust the median — the offer is too far below what the item
   should cost, which is the signature of a mislisting/refurb, not a deal.

The blended ``verdict`` flags the Bose-at-$46 case as SUSPICIOUS rather than a
great deal, while still passing a genuine value pick (Anker Q20i at $44.99).
"""
from __future__ import annotations

from dataclasses import dataclass

# How far below the fair price we still trust as a *real* deal. Beyond this, the
# gap is "too good to be true" — the model no longer believes the price.
SUSPICIOUS_RESIDUAL_FRAC = 0.70  # actual < 30% of fair price → too-good-to-be-true
DEAL_MEDIAN_FRAC = 0.15          # need >=15% under the market median to be a deal


def median_signal(actual: float, median: float) -> float:
    """Fraction below the same-query cross-source median. Positive = cheaper."""
    if median <= 0:
        return 0.0
    return (median - actual) / median


def fair_price(model, features) -> float:
    """The model's predicted fair price for one product's feature row."""
    import numpy as np

    row = np.asarray(features, dtype=float).reshape(1, -1)
    return float(model.predict(row)[0])


def residual(actual: float, fair: float) -> float:
    """Signed gap fair − actual (positive = actual is *below* fair = looks cheap)."""
    return fair - actual


def residual_fraction(actual: float, fair: float) -> float:
    """Residual as a fraction of the fair price (positive = below fair)."""
    if fair <= 0:
        return 0.0
    return (fair - actual) / fair


@dataclass
class Verdict:
    label: str            # "deal" | "suspicious" | "fair" | "overpriced"
    median_signal: float  # fraction below market median
    fair_price: float     # model's predicted fair price
    residual_frac: float  # (fair - actual) / fair
    reason: str


def verdict(
    actual: float,
    median: float,
    fair: float,
    *,
    deal_median_frac: float = DEAL_MEDIAN_FRAC,
    suspicious_residual_frac: float = SUSPICIOUS_RESIDUAL_FRAC,
) -> Verdict:
    """Blend the median signal and the model residual into one verdict.

    - **suspicious**: median says "great deal" but the price is implausibly far
      below the model's fair price (residual_frac >= ``suspicious_residual_frac``).
      This is the Bose-QC45-at-$46 trap.
    - **deal**: meaningfully under the median AND the model agrees it's plausible.
    - **overpriced**: above the market median.
    - **fair**: near the median, nothing special.
    """
    m = median_signal(actual, median)
    rf = residual_fraction(actual, fair)

    if m >= deal_median_frac and rf >= suspicious_residual_frac:
        return Verdict(
            "suspicious", m, fair, rf,
            f"{m * 100:.0f}% under median but {rf * 100:.0f}% under model fair "
            f"price ${fair:.0f} — too far below to be real (likely refurb/mislisted).",
        )
    if m >= deal_median_frac:
        return Verdict(
            "deal", m, fair, rf,
            f"{m * 100:.0f}% under the ${median:.2f} median and consistent with the "
            f"model's ${fair:.0f} fair price — a genuine value pick.",
        )
    if m < 0:
        return Verdict("overpriced", m, fair, rf, f"{-m * 100:.0f}% above the market median.")
    return Verdict("fair", m, fair, rf, "priced near the market median.")


def render_badge(deal_pct: float, residual_frac: float) -> str:
    """Map the two-signal score to a single display badge label.

    A thin presentation-layer wrapper over the same signals + thresholds that
    ``verdict`` uses, returning the uppercase badge the web UI paints on a card:

    - ``deal_pct``      — fraction below the same-query cross-source median
      (positive = cheaper than the market).
    - ``residual_frac`` — ``(fair - actual) / fair`` (positive = below model fair).

    Returns one of ``"DEAL" | "FAIR" | "SUSPICIOUS" | "OVERPRICED"``. The suspicious
    guard is checked first: it is the case where BOTH signals would otherwise shout
    "great deal", so it overrides rather than falls through (the Bose-QC45-at-$46
    trap). Kept consistent with ``verdict`` by sharing ``DEAL_MEDIAN_FRAC`` and
    ``SUSPICIOUS_RESIDUAL_FRAC``."""
    if deal_pct >= DEAL_MEDIAN_FRAC and residual_frac >= SUSPICIOUS_RESIDUAL_FRAC:
        return "SUSPICIOUS"
    if deal_pct >= DEAL_MEDIAN_FRAC:
        return "DEAL"
    if deal_pct < 0:
        return "OVERPRICED"
    return "FAIR"
