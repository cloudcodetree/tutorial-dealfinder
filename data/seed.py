"""Bulk-seed pgvector from the frozen snapshot + the Part-4 cached embeddings.

Loads every snapshot product and its committed 384-dim bge-small title vector
(no model run), then upserts all of them in one pass so `/semantic` can query
by meaning against a real HNSW index. Idempotent — `upsert` uses ON CONFLICT,
so re-running updates rows in place instead of duplicating them.

    DATABASE_URL=postgresql://dealfinder:dealfinder@localhost:5434/dealfinder python data/seed.py
"""
from __future__ import annotations

import numpy as np

from dealfinder.embed import load_title_embeddings
from dealfinder.pgstore import count, migrate, upsert
from dealfinder.snapshot import load_products

# The snapshot was collected under this anchor query; every row shares the label.
ANCHOR_QUERY = "noise cancelling headphones"


def seed() -> None:
    migrate()

    products = load_products()
    ids, vectors = load_title_embeddings()
    pos = {pid: i for i, pid in enumerate(ids)}

    rows, embs = [], []
    for p in products:
        if p.id not in pos:
            continue
        rows.append({
            "id": p.id, "title": p.title, "brand": p.brand, "source": p.source,
            "price": p.price, "currency": p.currency, "url": p.url, "image_url": p.image_url,
        })
        embs.append(np.asarray(vectors[pos[p.id]], dtype=np.float32))

    n = upsert(rows, embs, query=ANCHOR_QUERY)
    print(f"Seeded {n} products; total in DB: {count()}")


if __name__ == "__main__":
    seed()
