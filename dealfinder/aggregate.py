"""Tiered aggregation that avoids throttling.

Sources are grouped into tiers (cheap/reliable = low tier). We query tier by
tier and STOP as soon as we have enough deduped offers — so pricey, rate-limited
browser scrapers only run when the fast APIs came up short. A circuit breaker
benches any source that errors or throttles for a cooldown window, so one flaky
/ rate-limited source never gets hammered on the next search.

With real multi-source data the deal signal is the market itself: how far below
the median of all offers a price sits.
"""
from __future__ import annotations

import os
import statistics
import time

from .dedup import dedup_by_embedding
from .ingest import dedup_key
from .live_sources import LIVE_SOURCES

# Overridable without touching source (tests pin the 90.0 default).
COOLDOWN_SECONDS = float(os.getenv("DEALFINDER_COOLDOWN_SECONDS", "90"))
TARGET_RESULTS = int(os.getenv("DEALFINDER_TARGET_RESULTS", "12"))  # once we have this many deduped offers, stop escalating

_cooldown: dict[str, float] = {}  # source name → monotonic time it's benched until


def _benched(name: str) -> bool:
    return time.monotonic() < _cooldown.get(name, 0.0)


def _bench(name: str) -> None:
    _cooldown[name] = time.monotonic() + COOLDOWN_SECONDS


def _tier(s) -> int:
    return getattr(s, "tier", 5)


def _is_fallback(s) -> bool:
    return getattr(s, "fallback_only", False)


def aggregate(query: str, sources=LIVE_SOURCES, limit: int = 24, target: int = TARGET_RESULTS) -> dict:
    available = [s for s in sources if s.available() and not _benched(s.name)]
    real = [s for s in available if not _is_fallback(s)]

    products, live, throttled = [], [], []

    def run(src) -> None:
        try:
            found = src.search(query)
            if found:
                live.append(src.name)
                products.extend(found)
        except Exception:  # error or rate-limit → bench it, don't retry this round
            _bench(src.name)
            throttled.append(src.name)

    # cheapest/most-reliable tier first; stop escalating once we have enough
    for tier in sorted({_tier(s) for s in real}):
        for src in (s for s in real if _tier(s) == tier):
            run(src)
        if len({dedup_key(p) for p in products}) >= target:
            break

    # nothing from real sources → fall back to keyless (e.g. iTunes)
    if not products:
        for src in (s for s in available if _is_fallback(s)):
            run(src)

    best: dict[str, object] = {}
    for p in products:
        k = dedup_key(p)
        if k not in best or p.price < best[k].price:
            best[k] = p
    # semantic pass: collapse cross-retailer offers of the same product
    # (the exact-key pass above only merges byte-identical brand|title rows)
    items = dedup_by_embedding(list(best.values()))
    median = statistics.median([p.price for p in items]) if items else 0.0
    ranked = sorted(items, key=lambda p: p.price)[:limit]

    return {
        "query": query,
        "sources_live": live,
        "throttled": throttled,
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
