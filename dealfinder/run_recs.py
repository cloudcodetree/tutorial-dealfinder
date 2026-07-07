"""Demo both recommenders over the real snapshot and score CF offline.

content-based: "more like the Sony WH-1000XM5" via the cached title embeddings.
collaborative: "people who liked this also liked…" over the real interaction log.

Run:  python -m dealfinder.run_recs
"""
from __future__ import annotations

import numpy as np

from .ranking import ndcg_at_k, precision_at_k
from .recommend import (
    collaborative_recommend,
    load_interactions,
    similar_products,
)
from .snapshot import load_snapshot

K = 5


def main() -> None:
    # --- content-based: "more like this" over cached title embeddings ---
    ref = "Sony WH-1000XM5 Wireless Headphones"
    print(f'content-based — more like "{ref}":')
    for r in similar_products(ref, k=3):
        print(f"  ${r['price']:>7.2f}  [{r['category']}] {r['title']}")

    # --- collaborative: "people who liked these also liked" ---
    item_ids, R = load_interactions()
    titles = {row["id"]: row["title"] for row in load_snapshot()}
    idx = next(i for i, iid in enumerate(item_ids)
               if titles[iid] == ref)
    user = np.zeros(len(item_ids))
    user[idx] = 1
    print(f'\ncollaborative — a user who liked "{ref}":')
    for j in collaborative_recommend(user, R, k=3):
        print(f"  {titles[item_ids[j]][:50]}")

    # --- offline eval: leave-one-out, CF vs a popularity baseline ---
    popularity = list(np.argsort(-R.sum(axis=0)))
    cf_p, cf_n, pop_p = [], [], []
    for row in R:
        liked_idx = list(np.where(row > 0)[0])
        if len(liked_idx) < 2:
            continue
        held = liked_idx[-1]
        train = row.copy()
        train[held] = 0
        recs = collaborative_recommend(train, R, k=K)
        cf_p.append(precision_at_k(recs, {held}, K))
        cf_n.append(ndcg_at_k(recs, {held}, K))
        pop = [j for j in popularity if train[j] == 0][:K]
        pop_p.append(precision_at_k(pop, {held}, K))

    print(f"\noffline eval (leave-one-out, k={K}, {len(cf_p)} users):")
    print(f"  collaborative  precision@{K} = {np.mean(cf_p):.3f}   ndcg@{K} = {np.mean(cf_n):.3f}")
    print(f"  popularity     precision@{K} = {np.mean(pop_p):.3f}   (baseline)")


if __name__ == "__main__":
    main()
