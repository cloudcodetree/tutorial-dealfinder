"""Real neural embeddings on CPU via fastembed (ONNX — no GPU, no torch).

The model downloads once and then runs offline and deterministically. We embed a
short text built from each product so semantic search matches on *meaning*, not
just shared words.

Title embeddings are computed once and **cached** here (spec §9.5: Part 4
introduces + caches the title embeddings; Part 5 reuses them, Part 13 persists
them in pgvector — all from this one run). The committed cache lives at
``data/embeddings/<snapshot>.title-bge-small.npz`` so recommend/search stay
offline and reproducible.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .schema import Product

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None

# Where the committed title-embedding cache for the current snapshot lives.
_EMBED_DIR = Path(__file__).resolve().parent.parent / "data" / "embeddings"
_TITLE_CACHE = _EMBED_DIR / "electronics-2026-07.title-bge-small.npz"


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(_MODEL_NAME)
    return _model


def product_text(p: Product) -> str:
    """The text we embed: title + brand + category + key specs."""
    specs = " ".join(f"{k} {v}" for k, v in p.specs.items())
    return f"{p.title}. {p.brand or ''} {p.category}. {specs}".strip()


def embed_texts(texts: list[str]) -> np.ndarray:
    return np.array(list(_get_model().embed(texts)), dtype=float)


def load_title_embeddings(path: Path | str | None = None) -> tuple[list[str], np.ndarray]:
    """Load the committed ``(ids, vectors)`` title-embedding cache for the snapshot.

    This is the Part-4 cache every later part reuses, so no test needs to run the
    embedding model (which would download weights / add latency). Returns the item
    ids in cache order and the (n, 384) float matrix aligned to them.
    """
    p = Path(path) if path else _TITLE_CACHE
    # allow_pickle: the ``ids`` array is a numpy object array of strings. Safe —
    # this reads only our own committed in-repo cache, never untrusted input.
    with np.load(p, allow_pickle=True) as z:
        return [str(i) for i in z["ids"]], z["vectors"].astype(float)


def build_title_embeddings(items: list[dict], path: Path | str | None = None) -> np.ndarray:
    """Embed each snapshot row's title and persist an ``(ids, vectors)`` cache.

    Run once to (re)generate the committed cache after a snapshot refresh. Not
    exercised by the offline tests — they read the committed cache instead.
    """
    p = Path(path) if path else _TITLE_CACHE
    p.parent.mkdir(parents=True, exist_ok=True)
    ids = [r["id"] for r in items]
    vectors = embed_texts([r["title"] for r in items]).astype("float32")
    np.savez_compressed(p, ids=np.array(ids), model=np.array(_MODEL_NAME), vectors=vectors)
    return vectors
