"""A semantic cache: reuse a past answer when a new query *means* the same thing.

An exact-string cache misses "cheap 2p tent" vs "affordable two-person tent". A
semantic cache stores the query embedding and returns the cached value when a new
query is within a cosine threshold — a big cost/latency win on repetitive traffic.
"""
from __future__ import annotations

import numpy as np


class SemanticCache:
    def __init__(self, threshold: float = 0.95) -> None:
        self.threshold = threshold
        self._vecs: list[list[float]] = []
        self._vals: list = []

    def put(self, vec, value) -> None:
        self._vecs.append([float(x) for x in vec])
        self._vals.append(value)

    def get(self, vec):
        if not self._vecs:
            return None
        V = np.array(self._vecs)
        q = np.asarray(vec, dtype=float)
        sims = (V @ q) / (np.linalg.norm(V, axis=1) * np.linalg.norm(q) + 1e-9)
        i = int(np.argmax(sims))
        return self._vals[i] if sims[i] >= self.threshold else None
