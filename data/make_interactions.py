"""Generate a synthetic user×tent "likes" matrix with latent taste groups.

Real recommenders need interaction data. We invent four personas (ultralight,
premium, budget, family); each user belongs to one and mostly likes tents that
fit it. That gives the co-like structure collaborative filtering feeds on — and,
because personas are known, the recommendations are sensible to eyeball.

Run from the repo root:  python data/make_interactions.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from dealfinder.features import BRAND_TIER

rng = np.random.default_rng(7)
N_USERS = 60


def persona_likes(tent: dict, persona: str) -> bool:
    cap = int(tent["specs"]["capacity"])
    wkg = float(tent["specs"]["weight_kg"])
    tier = BRAND_TIER.get(tent["brand"] or "", 1)
    return {
        "ultralight": wkg < 1.8,
        "premium": tier == 3,
        "budget": tier == 1,
        "family": cap >= 3,
    }[persona]


def main() -> None:
    catalog = json.loads((Path(__file__).parent / "sample" / "catalog.json").read_text())
    ids = [t["id"] for t in catalog]
    personas = ["ultralight", "premium", "budget", "family"]

    matrix = []
    for _ in range(N_USERS):
        persona = personas[int(rng.integers(0, len(personas)))]
        row = [0] * len(catalog)
        for j, tent in enumerate(catalog):
            fit = persona_likes(tent, persona)
            p = 0.55 if fit else 0.05  # mostly like on-persona tents, rarely off
            if rng.random() < p:
                row[j] = 1
        if sum(row) == 0:  # guarantee at least one like
            row[int(rng.integers(0, len(catalog)))] = 1
        matrix.append(row)

    out = Path(__file__).parent / "sample" / "interactions.json"
    out.write_text(json.dumps({"item_ids": ids, "matrix": matrix}))
    likes = sum(sum(r) for r in matrix)
    print(f"wrote {N_USERS} users × {len(ids)} tents ({likes} likes) -> {out.relative_to(Path(__file__).parent.parent)}")


if __name__ == "__main__":
    main()
