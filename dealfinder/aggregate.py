"""Tiered aggregation that avoids throttling.

Sources are grouped into tiers (cheap/reliable = low tier). We query tier by
tier and STOP as soon as we have enough deduped offers — so pricey, rate-limited
browser scrapers only run when the fast APIs came up short. A circuit breaker
benches any source that errors or throttles for a cooldown window, so one flaky
/ rate-limited source never gets hammered on the next search.

With real multi-source data the deal signal is the market itself: how far below
the median of all offers a price sits.

Sources in a tier run concurrently, each bounded by a timeout (``timeout_s``), so
one slow store never holds the whole search; a source that misses the deadline is
benched like one that errored. The breaker state lives in this process on
purpose (spec §6.6): each Cloud Run instance learns a bad source on its own, so
the worst case is one wasted call per instance per cooldown window.
"""
from __future__ import annotations

import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from .dedup import dedup_by_embedding
from .ingest import dedup_key
from .live_sources import enabled_sources

# Overridable without touching source (tests pin the 90.0 default).
COOLDOWN_SECONDS = float(os.getenv("DEALFINDER_COOLDOWN_SECONDS", "90"))
TARGET_RESULTS = int(os.getenv("DEALFINDER_TARGET_RESULTS", "12"))  # once we have this many deduped offers, stop escalating
SOURCE_TIMEOUT_S = float(os.getenv("DEALFINDER_SOURCE_TIMEOUT_S", "8"))  # per source, per tier

_cooldown: dict[str, float] = {}  # source name → monotonic time it's benched until
_cooldown_lock = threading.Lock()


def _benched(name: str) -> bool:
    with _cooldown_lock:
        return time.monotonic() < _cooldown.get(name, 0.0)


def _bench(name: str) -> None:
    with _cooldown_lock:
        _cooldown[name] = time.monotonic() + COOLDOWN_SECONDS


def _utc_iso(dt: datetime) -> str:
    """``2026-10-26T12:00:00Z``: second precision, always UTC."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tier(s) -> int:
    return getattr(s, "tier", 5)


def _is_fallback(s) -> bool:
    return getattr(s, "fallback_only", False)


def aggregate(query: str, sources=None, limit: int = 24, target: int = TARGET_RESULTS,
              timeout_s: float = SOURCE_TIMEOUT_S) -> dict:
    if sources is None:
        sources = enabled_sources()
    available = [s for s in sources if s.available() and not _benched(s.name)]
    real = [s for s in available if not _is_fallback(s)]

    products, live, throttled, timed_out = [], [], [], []
    fetched: dict[int, str] = {}  # id(product) → when its source answered

    def timed_search(src):
        found = src.search(query)
        return found, datetime.now(timezone.utc)

    def run(batch) -> None:
        """Query one tier's sources at once; bench any that error or miss the deadline."""
        if not batch:
            return
        pool = ThreadPoolExecutor(max_workers=len(batch))
        futures = {pool.submit(timed_search, src): src for src in batch}
        _, pending = wait(futures, timeout=timeout_s)
        pool.shutdown(wait=False, cancel_futures=True)
        for fut, src in futures.items():  # submission order keeps results deterministic
            if fut in pending:
                _bench(src.name)
                throttled.append(src.name)
                timed_out.append(src.name)
                continue
            try:
                found, at = fut.result()
            except Exception:  # error or rate-limit → bench it, don't retry this round
                _bench(src.name)
                throttled.append(src.name)
                continue
            if found:
                live.append(src.name)
                products.extend(found)
                stamp = _utc_iso(at)
                fetched.update((id(p), stamp) for p in found)

    # cheapest/most-reliable tier first; stop escalating once we have enough
    for tier in sorted({_tier(s) for s in real}):
        run([s for s in real if _tier(s) == tier])
        if len({dedup_key(p) for p in products}) >= target:
            break

    # nothing from real sources → fall back to keyless (e.g. iTunes)
    if not products:
        run([s for s in available if _is_fallback(s)])

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
        "timed_out": timed_out,
        "median_price": round(median, 2),
        "count": len(ranked),
        "results": [
            {
                "id": p.id, "title": p.title, "brand": p.brand, "price": p.price,
                "source": p.source, "url": p.url, "image_url": p.image_url,
                "sku": p.sku, "regular_price": p.regular_price,
                "fetched_at": fetched.get(id(p)) or _utc_iso(datetime.now(timezone.utc)),
                "deal_pct": round((median - p.price) / median * 100, 1) if median else 0.0,
            }
            for p in ranked
        ],
    }
