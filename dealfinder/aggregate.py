"""Aggregate one search across every live source, dedup, and rank by value.

With real multi-source data there's no synthetic "fair price" — the deal signal
is the market itself: how far below the median of all offers a given price sits.
That's a real, source-agnostic deal score.
"""
from __future__ import annotations

import statistics

from .ingest import dedup_key
from .live_sources import LIVE_SOURCES


def aggregate(query: str, sources=LIVE_SOURCES, limit: int = 24) -> dict:
    products, live = [], []
    for s in sources:
        if not s.available():
            continue
        try:
            found = s.search(query)
            if found:
                live.append(s.name)
                products.extend(found)
        except Exception:  # one flaky source must not sink the search
            continue

    # dedup across sources, keeping the cheapest for each item
    best: dict[str, object] = {}
    for p in products:
        k = dedup_key(p)
        if k not in best or p.price < best[k].price:
            best[k] = p
    items = list(best.values())

    median = statistics.median([p.price for p in items]) if items else 0.0
    ranked = sorted(items, key=lambda p: p.price)[:limit]

    return {
        "query": query,
        "sources_live": live,
        "median_price": round(median, 2),
        "count": len(ranked),
        "results": [
            {
                "id": p.id, "title": p.title, "brand": p.brand, "price": p.price,
                "source": p.source, "url": p.url, "image_url": p.image_url,
                "deal_pct": round((median - p.price) / median * 100, 1) if median else 0.0,
            }
            for p in ranked
        ],
    }
