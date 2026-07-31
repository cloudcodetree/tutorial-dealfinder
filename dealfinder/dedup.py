"""Semantic (embedding) dedup — collapse cross-retailer offers of one product.

Part 1's ``dedup_key`` only merges byte-identical brand|title rows. This module
closes the gap it documents: titles that *mean* the same product but read
differently ("Sony WH-1000XM5 Wireless Industry Leading Noise Canceling
Headphones" vs "Sony WH-1000XM5 Noise Cancelling Headphones — Black") are
clustered by title-embedding cosine similarity and each cluster keeps its
cheapest offer.
"""

from __future__ import annotations

import re

import numpy as np
from fastembed import TextEmbedding

_model: TextEmbedding | None = None
_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=_EMBED_MODEL)
    return _model


def _embed(titles: list[str]) -> np.ndarray:
    """Return (N, 384) float32 array — cached model, no repeated downloads."""
    model = _get_model()
    vecs = list(model.embed(titles))
    return np.array(vecs, dtype=np.float32)


def _cosine_matrix(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    normed = vecs / np.where(norms > 0, norms, 1.0)
    return normed @ normed.T


_TOKEN = re.compile(r"[a-z0-9]+")


def _model_tokens(title: str) -> frozenset[str]:
    """Digit-bearing tokens — the closest thing a title has to a model number.

    'Sony WH-1000XM5 Wireless Headphones' → {'1000xm5'}; 'Bose QuietComfort 45'
    → {'45'}. Measured on the snapshot, cosine alone merges different products
    in the same family (XM5 ↔ XM6 scores 0.9251); model tokens are what
    actually separate them.
    """
    return frozenset(t for t in _TOKEN.findall(title.lower()) if any(c.isdigit() for c in t))


def _first_token(title: str) -> str:
    """Leading word — almost always the manufacturer in a normalized title."""
    m = _TOKEN.findall(title.lower())
    return m[0] if m else ""


def dedup_by_embedding(
    items: list,
    sim_threshold: float = 0.90,
    no_model_threshold: float = 0.95,
) -> list:
    """
    Cluster items that are cosine-similar AND look like the same product.

    Two titles merge only when all three hold:
      1. same leading (manufacturer) token — a Sony never merges with a Samsung
         just because both titles say "2.0 Channel Soundbar";
      2. their model tokens agree — equal digit-bearing token sets merge at
         ``sim_threshold``; if neither title carries a model token the bar rises
         to ``no_model_threshold`` (title wording is all we have, so demand more);
         mismatched model tokens never merge (XM5 ≠ XM6, QC45 ≠ QC Ultra);
      3. title-embedding cosine clears the applicable threshold.

    Within each cluster the cheapest item survives. Returns a new list — input
    is not mutated. Known residual failure mode: same brand + same model number
    across product lines (JBL *Tune* 770NC vs JBL *Live* 770NC) still merges —
    documented in Part 9, guarded downstream by the deal-score verdicts.
    """
    if not items:
        return []

    titles = [p.title for p in items]
    vecs = _embed(titles)
    sim = _cosine_matrix(vecs)
    n = len(items)
    models = [_model_tokens(t) for t in titles]
    brands = [_first_token(t) for t in titles]

    # union-find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    def same_product(i: int, j: int) -> bool:
        if brands[i] != brands[j]:
            return False
        if models[i] and models[j]:
            return models[i] == models[j] and sim[i, j] >= sim_threshold
        if not models[i] and not models[j]:
            return sim[i, j] >= no_model_threshold
        return False  # one has a model number, the other doesn't → not the same listing

    for i in range(n):
        for j in range(i + 1, n):
            if same_product(i, j):
                union(i, j)

    clusters: dict[int, list] = {}
    for i, p in enumerate(items):
        root = find(i)
        clusters.setdefault(root, []).append(p)

    kept = []
    for cluster in clusters.values():
        # cheapest first; ties broken by insertion order
        best = min(cluster, key=lambda p: p.price)
        kept.append(best)

    return kept
