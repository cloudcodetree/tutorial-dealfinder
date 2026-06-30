"""An evaluation harness — stop eyeballing quality, measure it.

A golden set (inputs with known-correct outputs), metrics over it, and an A/B
comparison you can gate a deploy on. This is what turns "seems better" into "+12%
exact-match, ship it" — and what runs in CI on every change.
"""
from __future__ import annotations

from typing import Callable

from .extract import ListingSpecs, rule_extract

FIELDS = ["brand", "capacity", "weight_kg", "season"]

# (listing, ground-truth specs) — the golden set, hand-labeled
GOLDEN: list[tuple[str, ListingSpecs]] = [
    ("TrailLite UL2 — ultralight 2-person tent, just 1.1kg, 3-season",
     ListingSpecs(brand="TrailLite", capacity=2, weight_kg=1.1, season=3)),
    ("SummitPro 4-season expedition tent, sleeps 4, 3.2 kg",
     ListingSpecs(brand="SummitPro", capacity=4, weight_kg=3.2, season=4)),
    ("BasecampCo family tent (sleeps 3), 2-season, 2400 g",
     ListingSpecs(brand="BasecampCo", capacity=3, weight_kg=2.4, season=2)),
    ("ValueOutdoors solo backpacker — 1 person, 3 season, 1.6kg",
     ListingSpecs(brand="ValueOutdoors", capacity=1, weight_kg=1.6, season=3)),
]


def field_accuracy(pred: ListingSpecs, gold: ListingSpecs) -> float:
    return sum(getattr(pred, f) == getattr(gold, f) for f in FIELDS) / len(FIELDS)


def exact_match(pred: ListingSpecs, gold: ListingSpecs) -> bool:
    return all(getattr(pred, f) == getattr(gold, f) for f in FIELDS)


def evaluate(extractor: Callable[[str], ListingSpecs], cases=GOLDEN) -> dict:
    preds = [extractor(text) for text, _ in cases]
    fa = [field_accuracy(p, g) for p, (_, g) in zip(preds, cases)]
    em = [exact_match(p, g) for p, (_, g) in zip(preds, cases)]
    return {"n": len(cases), "field_accuracy": sum(fa) / len(fa), "exact_match": sum(em) / len(em)}


def ab_compare(name_a: str, score_a: float, name_b: str, score_b: float) -> dict:
    winner = name_a if score_a >= score_b else name_b
    return {"winner": winner, "delta": round(abs(score_a - score_b), 3)}


def brand_only_extract(text: str) -> ListingSpecs:
    """A deliberately weak baseline — gets the brand, misses the rest."""
    return ListingSpecs(brand=rule_extract(text).brand)
