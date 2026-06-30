"""Demo both recommenders and score collaborative filtering offline.

Run:  python -m dealfinder.run_recs
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .features import feature_matrix
from .ranking import ndcg_at_k, precision_at_k
from .recommend import collaborative_recommend, content_recommend
from .schema import Product

K = 5


def main() -> None:
    catalog = [Product.model_validate(r) for r in json.loads(Path("data/sample/catalog.json").read_text())]
    titles = [p.title for p in catalog]
    X = feature_matrix(catalog)

    # --- content-based: "more like this" ---
    ref = 1
    print(f'content-based — more like "{titles[ref]}":')
    for j in content_recommend(ref, X, k=3):
        print(f"  {catalog[j].id}: {titles[j]}")

    data = json.loads(Path("data/sample/interactions.json").read_text())
    R = np.array(data["matrix"])

    # --- collaborative: "people who liked these also liked" ---
    u = 0
    liked = [titles[j] for j in np.where(R[u] > 0)[0]]
    print(f"\ncollaborative — user 0 liked: {', '.join(liked[:4])}{' …' if len(liked) > 4 else ''}")
    for j in collaborative_recommend(R[u], R, k=3):
        print(f"  {catalog[j].id}: {titles[j]}")

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
