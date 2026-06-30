"""Offline ranking metrics — how good is a recommended list, before any user sees it.

These are the standard way to compare recommenders without an A/B test:
precision@k and recall@k count hits in the top-k; NDCG also rewards putting the
hits *higher* in the list.
"""
from __future__ import annotations

import numpy as np


def precision_at_k(recommended: list, relevant: set, k: int) -> float:
    rec_k = recommended[:k]
    hits = sum(1 for r in rec_k if r in relevant)
    return hits / k


def recall_at_k(recommended: list, relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    rec_k = recommended[:k]
    hits = sum(1 for r in rec_k if r in relevant)
    return hits / len(relevant)


def _dcg(rels: list[float]) -> float:
    rels = np.asarray(rels, dtype=float)
    discounts = 1.0 / np.log2(np.arange(2, len(rels) + 2))
    return float(np.sum(rels * discounts))


def ndcg_at_k(recommended: list, relevant: set, k: int) -> float:
    """Normalised discounted cumulative gain — 1.0 is the perfect ordering."""
    gains = [1.0 if r in relevant else 0.0 for r in recommended[:k]]
    ideal = [1.0] * min(len(relevant), k) + [0.0] * max(0, k - len(relevant))
    idcg = _dcg(ideal)
    return _dcg(gains) / idcg if idcg > 0 else 0.0
