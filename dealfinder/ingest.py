"""Merge products from many sources into one deduplicated catalog."""

from __future__ import annotations

from dealfinder.schema import Product
from dealfinder.sources import DealSource


def dedup_key(p: Product) -> str:
    """Same product across sources should collapse: normalize brand + title."""
    return f"{(p.brand or '').strip().lower()}|{p.title.strip().lower()}"


def ingest(sources: list[DealSource]) -> list[Product]:
    """Pull from every source; when the same product appears twice, keep the cheapest."""
    best: dict[str, Product] = {}
    for src in sources:
        for p in src.products():
            k = dedup_key(p)
            if k not in best or p.price < best[k].price:
                best[k] = p
    return list(best.values())
