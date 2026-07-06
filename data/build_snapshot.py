#!/usr/bin/env python3
"""Build a versioned, *real* electronics snapshot for the DealFinder course.

Why this exists
---------------
The course teaches on REAL data, but training a price model, running an eval
gate, and quoting concrete numbers all need a *reproducible* corpus. Live APIs
change every call. The professional fix (and a genuine lesson) is a versioned
data snapshot: pull real listings once, freeze them, commit them, and train /
test / eval against the frozen-but-real file. The live aggregator still runs
live in the parts that are about liveness.

This script hits the already-running DealFinder app (whose process holds the API
keys) so we never read .env directly. It pulls a curated spread of broad
consumer-electronics queries, drops eBay results (the app runs eBay in SANDBOX
mode = synthetic test data), dedupes by id, and writes a single dated JSON.

Usage
-----
    python3 data/build_snapshot.py                 # default query set -> data/snapshots/electronics-YYYY-MM.json
    APP=http://127.0.0.1:8000 python3 data/build_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP = os.environ.get("APP", "http://127.0.0.1:8000").rstrip("/")

# Curated broad-electronics queries. Each carries a coarse `category` so the
# snapshot has category diversity for feature engineering + categorical
# encodings (a laptop and an earbud don't share numeric specs — category is the
# feature that lets one model span them).
QUERIES: list[tuple[str, str]] = [
    ("noise cancelling headphones", "audio"),
    ("wireless earbuds", "audio"),
    ("bluetooth speaker", "audio"),
    ("soundbar", "audio"),
    ("gaming laptop", "computers"),
    ("4k monitor", "displays"),
    ("mechanical keyboard", "peripherals"),
    ("gaming mouse", "peripherals"),
    ("1080p webcam", "peripherals"),
    ("external ssd 1tb", "storage"),
    ("usb c hub", "accessories"),
    ("power bank", "accessories"),
    ("android tablet", "mobile"),
    ("smartwatch", "wearables"),
    ("robot vacuum", "smart-home"),
    ("wifi security camera", "smart-home"),
    ("kindle e-reader", "misc"),
    ("graphics card rtx", "components"),
]

# eBay is configured with SBX (sandbox) credentials in this environment, so its
# results are eBay's synthetic test catalog — not real market data. Exclude any
# item whose source marketplace is in this set to keep the corpus genuinely real.
EXCLUDE_SOURCE_PREFIXES = ("eBay",)


def fetch(query: str, timeout: int = 70) -> dict:
    url = f"{APP}/search?q=" + urllib.parse.quote(query)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def excluded(source: str) -> bool:
    return any((source or "").startswith(p) for p in EXCLUDE_SOURCE_PREFIXES)


def main() -> int:
    now = datetime.now(timezone.utc)
    out_dir = Path(__file__).resolve().parent / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"electronics-{now:%Y-%m}.json"

    items: list[dict] = []
    seen: set[str] = set()
    sources_seen: dict[str, int] = {}
    per_query: list[dict] = []

    for query, category in QUERIES:
        try:
            res = fetch(query)
        except Exception as e:  # noqa: BLE001 — a flaky live source shouldn't kill the pull
            print(f"  ! {query!r} failed: {e}", file=sys.stderr)
            per_query.append({"query": query, "category": category, "kept": 0, "error": str(e)})
            continue

        median = res.get("median_price")
        kept = 0
        for it in res.get("results", []):
            src = it.get("source", "")
            if excluded(src):
                continue
            pid = it.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            marketplace = (src.split(":", 1)[0] or "unknown")
            sources_seen[marketplace] = sources_seen.get(marketplace, 0) + 1
            items.append({
                "id": pid,
                "query": query,
                "category": category,
                "title": it.get("title"),
                "brand": it.get("brand"),
                "price": it.get("price"),
                "currency": it.get("currency", "USD"),
                "source": src,
                "marketplace": marketplace,
                "url": it.get("url"),
                "image_url": it.get("image_url"),
                "deal_pct": it.get("deal_pct"),
                "median_price_at_capture": median,
            })
            kept += 1
        per_query.append({
            "query": query, "category": category, "kept": kept,
            "median_price": median, "sources_live": res.get("sources_live", []),
            "throttled": res.get("throttled", []),
        })
        print(f"  {query:32s} [{category:11s}] kept {kept:2d}  (median ${median})")
        time.sleep(1.5)  # be polite to the live sources

    snapshot = {
        "meta": {
            "created_at": now.isoformat(),
            "domain": "consumer-electronics",
            "source_app": f"{APP}/search",
            "excluded_sources": ["eBay (sandbox test data in this environment)"],
            "n_queries": len(QUERIES),
            "n_items": len(items),
            "sources_seen": sources_seen,
            "note": "Frozen real-data corpus. Regenerate with data/build_snapshot.py "
                    "against a running DealFinder app.",
            "per_query": per_query,
        },
        "items": items,
    }

    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(items)} real items across {len(QUERIES)} queries -> {out_path}")
    print(f"Sources: {sources_seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
