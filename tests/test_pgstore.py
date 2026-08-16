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


def test_rls_isolates_tenants():
    # The ENFORCEMENT half of multi-tenancy: Row-Level Security guarantees a tenant
    # only ever sees its own rows — even for the SAME product id (composite key
    # keeps them distinct), and even though the app connects as a superuser login
    # role (pgstore SET ROLEs to a non-superuser app role so the policy applies).
    url = _db()
    vec = [1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2)
    a = [{"id": "iso-x", "title": "Alpha Widget", "brand": "A", "source": "S", "price": 10, "url": "", "image_url": None}]
    b = [{"id": "iso-x", "title": "Beta Gadget", "brand": "B", "source": "S", "price": 20, "url": "", "image_url": None}]
    pgstore.upsert(a, [vec], query="iso", tenant="tenant-a", url=url)
    pgstore.upsert(b, [vec], query="iso", tenant="tenant-b", url=url)

    titles_a = {r["title"] for r in pgstore.semantic_search(vec, k=10, tenant="tenant-a", url=url)}
    titles_b = {r["title"] for r in pgstore.semantic_search(vec, k=10, tenant="tenant-b", url=url)}
    assert "Alpha Widget" in titles_a and "Beta Gadget" not in titles_a
    assert "Beta Gadget" in titles_b and "Alpha Widget" not in titles_b

    # Same id under two tenants coexist (composite PK), each private to its tenant.
    assert pgstore.count(tenant="tenant-a", url=url) >= 1
    assert pgstore.count(tenant="tenant-b", url=url) >= 1
