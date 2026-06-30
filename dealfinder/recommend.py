"""Two ways to recommend — the two that every recsys starts with.

content_recommend: "more like this one" — similarity over a product's own
features. Works on day one, even with zero user history (no cold-start problem).

collaborative_recommend: "people who liked this also liked…" — similarity learned
purely from who-liked-what, no product features at all. Needs interaction data
but captures taste a feature vector can't.
"""
from __future__ import annotations

import numpy as np


def _cosine_sim(A: np.ndarray) -> np.ndarray:
    A = np.asarray(A, dtype=float)
    norm = np.linalg.norm(A, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    U = A / norm
    return U @ U.T


def _standardize(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


def content_recommend(idx: int, X: np.ndarray, k: int = 3) -> list[int]:
    """Top-k items most similar to item `idx` by standardized feature cosine."""
    sims = _cosine_sim(_standardize(X))[idx]
    order = np.argsort(-sims)
    return [int(j) for j in order if j != idx][:k]


def collaborative_recommend(user_row: list, R: np.ndarray, k: int = 3) -> list[int]:
    """Item-item CF: score items by similarity to what the user already liked."""
    R = np.asarray(R, dtype=float)
    item_sim = _cosine_sim(R.T)  # items × items, from co-likes across users
    liked = np.where(np.asarray(user_row, dtype=float) > 0)[0]
    scores = item_sim[liked].sum(axis=0) if len(liked) else np.zeros(R.shape[1])
    scores[liked] = -np.inf  # never recommend something already liked
    order = np.argsort(-scores)
    return [int(j) for j in order if np.isfinite(scores[j])][:k]
