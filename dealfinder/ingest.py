"""Merge products from many sources into one deduplicated catalog."""

from __future__ import annotations

from dealfinder.schema import Product
from dealfinder.sources import DealSource


def dedup_key(p: Product) -> str:
    """Exact-match collision key: same brand + title (case-insensitive).

    Collapses byte-identical duplicates (e.g. a feed returning the same row twice).
    It does NOT merge the same product across retailers — the raw brand is a
    retailer string and titles vary between stores, so cross-retailer offers get
    distinct keys and are intentionally kept for price comparison. Recognizing
    those as one product is the semantic (cosine) dedup in Part 9.
    """
    return f"{(p.brand or '').strip().lower()}|{p.title.strip().lower()}"


def ingest(sources: list[DealSource]) -> list[Product]:
    """Pull from every source; when the exact same product appears twice, keep the cheapest."""
    best: dict[str, Product] = {}
    for src in sources:
        for p in src.products():
            k = dedup_key(p)
            if k not in best or p.price < best[k].price:
                best[k] = p
    return list(best.values())
