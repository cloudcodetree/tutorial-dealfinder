"""Generate a real-item user×listing "likes" matrix with latent taste cohorts.

Real recommenders need interaction data. We take a legible slice of the frozen
electronics snapshot (the 15 "noise cancelling headphones" + a handful of other
audio, keyboards and wearables) and invent cohorts with a shared taste — Sony NC
fans, flagship-ANC fans, the budget-ANC crowd, an earbuds cohort, and so on. Each
user mostly likes their cohort's items, giving collaborative filtering the co-like
structure it feeds on: someone who liked the Sony WH-1000XM5 gets the WH-1000XM6.

Deterministic (seed=7) so the committed ``interactions.json`` reproduces exactly.

Run from the repo root:  python data/make_interactions.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from dealfinder.snapshot import load_snapshot

SNAPSHOT = "electronics-2026-07.json"
USERS_PER_COHORT = 12


def _catalog(items: list[dict]) -> list[dict]:
    """A compact, interpretable slice of the snapshot to build likes over."""
    def by_query(q, n):
        return [i for i in items if i["query"] == q][:n]

    nch = [i for i in items if i["query"] == "noise cancelling headphones"]  # all 15
    extra = (by_query("wireless earbuds", 3) + by_query("bluetooth speaker", 2)
             + by_query("mechanical keyboard", 2) + by_query("smartwatch", 2))
    return nch + extra


def main() -> None:
    items = load_snapshot(str(Path(__file__).parent / "snapshots" / SNAPSHOT))
    catalog = _catalog(items)
    ids = [i["id"] for i in catalog]
    title_to_idx = {i["title"]: k for k, i in enumerate(catalog)}

    def idx(needle: str) -> int:
        return next(k for t, k in title_to_idx.items() if needle in t)

    # Cohorts of item indices with shared taste (resolved by title so the slice
    # can shift without silently mislabeling a cohort).
    cohorts = {
        "sony_nc": [idx("Sony WH-1000XM5 Wireless Headphones"), idx("WH-1000XM5 Wireless Noise-Canceling"),
                    idx("WH-1000XM6"), idx("Sony WH-CH720N Noise"), idx("Sony WH-CH720N/P")],
        "flagship_anc": [idx("Sony WH-1000XM5 Wireless Headphones"), idx("Bose QuietComfort Noise"),
                         idx("WH-1000XM6"), idx("Bose QuietComfort Ultra"), idx("Beats Studio Pro")],
        "budget_anc": [idx("Anker Soundcore Q20i"), idx("JBL Tune 770NC"),
                       idx("Soundcore Space 2"), idx("Cowin SE7")],
        "earbuds": [idx("ProBuds"), idx("Go Air Pop"), idx("Pop+")],
        "keyboards": [idx("HyperX"), idx("Glorious")],
        "wearables": [idx("Armitron"), idx("Withit")],
    }

    rng = np.random.default_rng(7)
    matrix: list[list[int]] = []
    for members in cohorts.values():
        for _ in range(USERS_PER_COHORT):
            row = np.zeros(len(ids), dtype=int)
            for m in members:
                if rng.random() < 0.85:  # mostly like your cohort's items
                    row[m] = 1
            for _ in range(int(rng.integers(0, 2))):  # a little cross-cohort noise
                row[int(rng.integers(0, len(ids)))] = 1
            matrix.append(row.tolist())

    out = Path(__file__).parent / "sample" / "interactions.json"
    out.write_text(json.dumps({
        "item_ids": ids,
        "titles": [i["title"] for i in catalog],
        "matrix": matrix,
    }))
    likes = sum(sum(r) for r in matrix)
    print(f"wrote {len(matrix)} users × {len(ids)} listings ({likes} likes) "
          f"-> {out.relative_to(Path(__file__).parent.parent)}")


if __name__ == "__main__":
    main()
