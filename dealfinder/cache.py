"""A semantic cache: reuse a past answer when a new query *means* the same thing.

An exact-string cache misses "cheap 2p tent" vs "affordable two-person tent". A
semantic cache stores the query embedding and returns the cached value when a new
query is within a cosine threshold — a big cost/latency win on repetitive traffic.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

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


class TTLCache:
    """An exact-key cache whose entries expire. Past `maxsize` the least recently used go
    first. Thread-safe, because FastAPI runs sync routes on a thread pool."""

    def __init__(self, maxsize: int = 512, ttl_s: float = 900, clock: Callable[[], float] = time.monotonic):
        self.maxsize, self.ttl_s, self._clock = maxsize, ttl_s, clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if self._clock() >= entry[0]:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return entry[1]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self.ttl_s, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data)
