"""An evaluation harness — stop eyeballing quality, measure it.

The task under test is the one the whole course is about: *given a pile of real
listings, does the ranker put genuine deals at the top?* We hand-label a golden
set drawn from the frozen snapshot (20 items: all 15 "noise cancelling
headphones" + 5 cross-category), each tagged ``deal | fair | suspicious |
overpriced``, then measure **precision@5** — of the five items a ranker surfaces
first, how many are truly deals.

The one eval-gate metric course-wide is ``precision@5 >= 0.80`` (spec §9.4). The
A/B here is the through-line of Part 3: the naive **median-only** ranker gets
fooled by the too-good-to-be-true traps (the $46 Bose, the $10.75 Kindle) and
misses the gate; the **two-signal** ranker (median blended with the model
residual guard) clears it. That's a measured "+X precision, ship it," not a vibe.
"""
from __future__ import annotations

from typing import Callable

from .dealmodel import LinearModel
from .dealscore import fair_price, median_signal, residual_fraction
from .features import feature_matrix, featurize
from .schema import Product
from .snapshot import load_products, load_snapshot

# The one course-wide eval gate (spec §9.4).
GATE_K = 5
GATE_PRECISION = 0.80
SUSPICIOUS_RESIDUAL_FRAC = 0.70  # matches dealscore.py's trap threshold

# ---------------------------------------------------------------------------
# The golden set — 20 hand-labeled real items (spec §9.4).
# Items are named by a stable title substring so the labels survive any change
# to the opaque snapshot ids. Labels are the frozen ground truth (they agree with
# the pinned hero-cast verdicts in spec §9.1).
# ---------------------------------------------------------------------------
# 15 "noise cancelling headphones" (the full anchor subset) …
_HEADPHONE_LABELS: list[tuple[str, str]] = [
    ("Cowin SE7", "suspicious"),
    ("Anker Soundcore Q20i", "deal"),
    ("Bose QuietComfort 45", "suspicious"),
    ("JBL Tune 770NC", "deal"),
    ("Sony WH-CH720N Noise", "deal"),
    ("Sony WH-CH720N/P", "deal"),
    ("Soundcore Space 2", "deal"),
    ("Sony WH-1000XM5 Wireless Headphones", "fair"),
    ("Skullcandy Crusher ANC 2", "overpriced"),
    ("JBL Live 770NC", "overpriced"),
    ("WH-1000XM5 Wireless Noise-Canceling", "overpriced"),
    ("Beats Studio Pro", "overpriced"),
    ("Bose QuietComfort Noise Cancelling", "overpriced"),
    ("Sony WH-1000XM6", "overpriced"),
    ("Bose QuietComfort Ultra", "overpriced"),
]
# … + 5 cross-category items that stress the two-signal score.
_CROSS_LABELS: list[tuple[str, str]] = [
    ("Kindle Paperwhite", "suspicious"),          # $10.75 mislisting/accessory trap
    ("Samsung Galaxy Tab A11+", "suspicious"),    # $15 flagship-ish tablet — too cheap
    ("Armitron Link Smart Watch", "deal"),        # $39.88 honest budget wearable
    ("Arlo Ultra 3", "overpriced"),               # $372.90 well above its market
    ("PNY NVIDIA RTX PRO 6000", "overpriced"),    # $13,599 mispriced outlier
]
GOLDEN_LABELS: list[tuple[str, str]] = _HEADPHONE_LABELS + _CROSS_LABELS


def _resolve(items: list[dict], needle: str) -> dict:
    """Find the one snapshot row whose title contains ``needle`` (case-insensitive)."""
    hits = [r for r in items if needle.lower() in r["title"].lower()]
    if not hits:
        raise KeyError(f"no snapshot item matches {needle!r}")
    return hits[0]


def load_golden(path: str | None = None) -> list[dict]:
    """Materialize the golden set as rows: ``{id, title, category, price, median, label}``."""
    items = load_snapshot(path)
    golden: list[dict] = []
    for needle, label in GOLDEN_LABELS:
        r = _resolve(items, needle)
        golden.append(
            {
                "id": r["id"], "title": r["title"], "category": r["category"],
                "price": float(r["price"]),
                "median": float(r["median_price_at_capture"]),
                "label": label,
            }
        )
    return golden


# ---------------------------------------------------------------------------
# Rankers — order the golden items by "how good a deal each looks".
# ---------------------------------------------------------------------------
def median_only_ranker(golden: list[dict]) -> list[dict]:
    """The naive Part-3 signal: rank purely by % below the same-query median.

    Fast, but the too-good-to-be-true traps (the $46 Bose, the $10.75 Kindle)
    top the list — exactly the false positives the model residual is there for.
    """
    return sorted(golden, key=lambda g: -median_signal(g["price"], g["median"]))


def two_signal_ranker(golden: list[dict], products: list[Product] | None = None) -> list[dict]:
    """The §4 blend: median signal, but demote anything the model flags as a trap.

    A per-category linear price model gives a fair price; when an item is both far
    under the median AND implausibly far under its fair price (residual_frac >
    0.70), it's pushed below the honest deals rather than rewarded.
    """
    products = products if products is not None else load_products()
    by_cat: dict[str, list[Product]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    models = {
        c: LinearModel().fit(feature_matrix(ps), [p.price for p in ps])
        for c, ps in by_cat.items()
        if len(ps) >= 3
    }
    by_id = {p.id: p for p in products}

    def score(g: dict) -> float:
        m = median_signal(g["price"], g["median"])
        model = models.get(g["category"])
        p = by_id.get(g["id"])
        if model is None or p is None:
            return m
        rf = residual_fraction(p.price, fair_price(model, featurize(p)))
        if m >= 0.15 and rf > SUSPICIOUS_RESIDUAL_FRAC:  # a trap → demote below real deals
            return m - 1.0
        return m

    return sorted(golden, key=lambda g: -score(g))


# ---------------------------------------------------------------------------
# Metric + gate + A/B.
# ---------------------------------------------------------------------------
def precision_at_k(ranked: list[dict], k: int = GATE_K) -> float:
    """Fraction of the top-k ranked items that are truly labeled ``deal``."""
    top = ranked[:k]
    return sum(1 for g in top if g["label"] == "deal") / max(1, len(top))


def evaluate(ranker: Callable[[list[dict]], list[dict]], golden: list[dict] | None = None) -> dict:
    """Run a ranker over the golden set and report precision@5 + the gate."""
    golden = golden if golden is not None else load_golden()
    ranked = ranker(golden)
    p_at_5 = precision_at_k(ranked, GATE_K)
    return {
        "n": len(golden),
        "precision_at_5": p_at_5,
        "gate": GATE_PRECISION,
        "passes_gate": p_at_5 >= GATE_PRECISION,
        "top5": [{"title": g["title"], "label": g["label"]} for g in ranked[:GATE_K]],
    }


def ab_compare(name_a: str, score_a: float, name_b: str, score_b: float) -> dict:
    """Pick the higher-scoring system and report the delta (ties → A)."""
    winner = name_a if score_a >= score_b else name_b
    return {"winner": winner, "delta": round(abs(score_a - score_b), 3)}
