"""pgvector store integration test — runs when a DB is reachable, skips otherwise
(keeps the suite offline-green in CI; real when DATABASE_URL points at pgvector)."""
import os

import pytest

from dealfinder import pgstore


def _db():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        pgstore.migrate(url)
    except Exception as e:  # DB not reachable in this environment
        pytest.skip(f"db unavailable: {e}")
    return url


def test_upsert_and_semantic_search_ranks_by_meaning():
    url = _db()
    prods = [
        {"id": "test-tent", "title": "Tent", "brand": "B", "source": "S", "price": 100, "url": "", "image_url": None},
        {"id": "test-buds", "title": "Headphones", "brand": "B", "source": "S", "price": 50, "url": "", "image_url": None},
    ]
    # distinct unit vectors (no model needed → deterministic)
    embs = [[1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2),
            [0.0, 1.0] + [0.0] * (pgstore.EMBED_DIM - 2)]
    pgstore.upsert(prods, embs, query="test", url=url)

    hits = pgstore.semantic_search([1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2), k=1, url=url)
    assert hits[0]["id"] == "test-tent"          # nearest to the tent vector
    assert hits[0]["similarity"] > 0.9
