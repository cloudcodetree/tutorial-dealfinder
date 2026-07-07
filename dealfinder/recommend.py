"""Two ways to recommend — the two that every recsys starts with — over the
REAL snapshot catalog.

content_recommend: "more like this one" — similarity over an item's own
representation. For broad electronics the representation that works is the
**cached fastembed title embedding** (spec §9.5), so "more like the Sony
WH-1000XM5" returns other real audio items, not just anything with an overlapping
word. Works on day one, even with zero user history (no cold-start problem).

collaborative_recommend: "people who liked this also liked…" — similarity learned
purely from who-liked-what, no item features at all. Needs interaction data but
captures taste a feature vector can't. Here it runs over a small real interaction
log keyed to snapshot ids (``data/sample/interactions.json``).

The low-level primitives (``content_recommend``, ``collaborative_recommend``) are
representation-agnostic — they take any matrix — so the same code powers the
feature-vector demo, the title-embedding recommender, and the CF log.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .embed import load_title_embeddings
from .schema import Product
from .snapshot import load_products

_INTERACTIONS = Path(__file__).resolve().parent.parent / "data" / "sample" / "interactions.json"


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


def content_recommend(idx: int, X: np.ndarray, k: int = 3, *, standardize: bool = True) -> list[int]:
    """Top-k items most similar to item `idx` by feature cosine.

    ``standardize`` z-scores columns first (right for small hand-feature vectors
    of differing scale); pass ``standardize=False`` for already-normalized dense
    embeddings, where per-column z-scoring would distort the geometry.
    """
    M = _standardize(X) if standardize else X
    sims = _cosine_sim(M)[idx]
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


# ---------------------------------------------------------------------------
# Snapshot-backed convenience layer (real items, cached title embeddings).
# ---------------------------------------------------------------------------
def load_catalog_embeddings(
    products: list[Product] | None = None,
) -> tuple[list[Product], np.ndarray]:
    """Align the frozen snapshot's products to their cached title embeddings.

    Reuses the Part-4 committed embedding cache (no model run), returning the
    products and an ``(n, 384)`` matrix in the same order.
    """
    products = products if products is not None else load_products()
    ids, vectors = load_title_embeddings()
    pos = {pid: i for i, pid in enumerate(ids)}
    rows = np.array([vectors[pos[p.id]] for p in products], dtype=float)
    return products, rows


def similar_products(title_substring: str, k: int = 5) -> list[dict]:
    """"More like this" over real items — e.g. ``similar_products("WH-1000XM5")``.

    Content-based on the cached title embeddings, so neighbors are semantically
    close real listings (other Sony/premium audio), with their price attached.
    """
    products, emb = load_catalog_embeddings()
    idx = next(i for i, p in enumerate(products) if title_substring.lower() in p.title.lower())
    recs = content_recommend(idx, emb, k, standardize=False)
    return [
        {"id": products[j].id, "title": products[j].title,
         "price": products[j].price, "category": products[j].category}
        for j in recs
    ]


def load_interactions(path: Path | str | None = None) -> tuple[list[str], np.ndarray]:
    """Load the real interaction log: ``(item_ids, users×items 0/1 matrix)``."""
    data = json.loads(Path(path or _INTERACTIONS).read_text())
    return data["item_ids"], np.array(data["matrix"], dtype=float)
