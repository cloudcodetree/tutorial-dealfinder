"""Retrieval over the catalog: semantic (vectors), keyword (BM25), fused (RRF),
then reranked by value.

Each piece is small and independently testable. The neural embedding lives in
embed.py; here we only need the vectors, so the math stays pure and offline.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

_tok = lambda s: re.findall(r"[a-z0-9]+", s.lower())  # noqa: E731


def cosine_rank(query_vec: np.ndarray, doc_vecs: np.ndarray, k: int):
    """Rank docs by cosine similarity to the query vector."""
    q = np.asarray(query_vec, dtype=float)
    q = q / (np.linalg.norm(q) or 1.0)
    D = np.asarray(doc_vecs, dtype=float)
    D = D / (np.linalg.norm(D, axis=1, keepdims=True) + 1e-9)
    sims = D @ q
    order = np.argsort(-sims)
    return [(int(i), float(sims[i])) for i in order[:k]]


class BM25:
    """Classic Okapi BM25 keyword ranking — exact-term matching with saturation."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = [_tok(d) for d in docs]
        self.k1, self.b = k1, b
        self.N = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / max(1, self.N)
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        self.idf = {w: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for w, n in df.items()}

    def search(self, query: str, k: int):
        q = _tok(query)
        scored = []
        for i, d in enumerate(self.docs):
            tf = Counter(d)
            s = 0.0
            for w in q:
                if w not in tf:
                    continue
                f = tf[w]
                s += self.idf.get(w, 0.0) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl)
                )
            scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return [(i, s) for i, s in scored[:k] if s > 0]


def rrf_fuse(rankings: list[list[int]], k: int = 60, top: int | None = None):
    """Reciprocal Rank Fusion — combine ranked lists without tuning weights."""
    scores = Counter()
    for r in rankings:
        for rank, doc in enumerate(r):
            scores[doc] += 1.0 / (k + rank + 1)
    fused = [d for d, _ in sorted(scores.items(), key=lambda x: -x[1])]
    return fused[:top] if top else fused


def value_rerank(doc_ids: list, deal_scores: dict, alpha: float = 0.5) -> list:
    """Blend retrieval relevance (by rank) with the Part-3 deal score."""
    n = len(doc_ids)
    rel = {d: 1 - i / max(1, n - 1) for i, d in enumerate(doc_ids)}
    combined = {
        d: (1 - alpha) * rel[d] + alpha * max(0.0, deal_scores.get(d, 0.0))
        for d in doc_ids
    }
    return sorted(doc_ids, key=lambda d: -combined[d])
