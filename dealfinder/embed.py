"""Real neural embeddings on CPU via fastembed (ONNX — no GPU, no torch).

The model downloads once and then runs offline and deterministically. We embed a
short text built from each product so semantic search matches on *meaning*, not
just shared words.
"""
from __future__ import annotations

import numpy as np

from .schema import Product

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None


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
