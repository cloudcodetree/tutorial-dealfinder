"""pgvector store integration test — runs when a DB is reachable, skips otherwise
(keeps the suite offline-green in CI; real when DATABASE_URL points at pgvector)."""
import psycopg
import pytest

from dealfinder import pgstore


@pytest.fixture
def clean_offers(db):
    """Delete every offer these tests create, so reruns stay deterministic."""
    yield db
    with psycopg.connect(db) as c:
        c.execute("delete from dealfinder.offers where id like 'test-%' or id like 'iso-%' or id like 'emb-%'"
                  " or id in ('ebay-1', 'bestbuy-77')")


def test_upsert_and_semantic_search_ranks_by_meaning(clean_offers):
    url = clean_offers
    prods = [
        {"id": "test-tent", "title": "Tent", "brand": "B", "source": "BestBuy", "price": 100, "url": "", "image_url": None},
        {"id": "test-buds", "title": "Headphones", "brand": "B", "source": "BestBuy", "price": 50, "url": "", "image_url": None},
    ]
    # distinct unit vectors (no model needed → deterministic)
    embs = [[1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2),
            [0.0, 1.0] + [0.0] * (pgstore.EMBED_DIM - 2)]
    pgstore.upsert(prods, embs, url=url)

    hits = pgstore.semantic_search([1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2), k=1, url=url)
    assert hits[0]["id"] == "test-tent"          # nearest to the tent vector
    assert hits[0]["similarity"] > 0.9


def test_rls_isolates_tenants(clean_offers):
    # The ENFORCEMENT half of multi-tenancy: Row-Level Security guarantees a tenant
    # only ever sees its own rows — even for the SAME product id (composite key
    # keeps them distinct), and even though the app connects as a superuser login
    # role (pgstore SET ROLEs to a non-superuser app role so the policy applies).
    url = clean_offers
    vec = [1.0, 0.0] + [0.0] * (pgstore.EMBED_DIM - 2)
    a = [{"id": "iso-x", "title": "Alpha Widget", "brand": "A", "source": "BestBuy", "price": 10, "url": "", "image_url": None}]
    b = [{"id": "iso-x", "title": "Beta Gadget", "brand": "B", "source": "BestBuy", "price": 20, "url": "", "image_url": None}]
    pgstore.upsert(a, [vec], tenant="tenant-a", url=url)
    pgstore.upsert(b, [vec], tenant="tenant-b", url=url)

    titles_a = {r["title"] for r in pgstore.semantic_search(vec, k=10, tenant="tenant-a", url=url)}
    titles_b = {r["title"] for r in pgstore.semantic_search(vec, k=10, tenant="tenant-b", url=url)}
    assert "Alpha Widget" in titles_a and "Beta Gadget" not in titles_a
    assert "Beta Gadget" in titles_b and "Alpha Widget" not in titles_b

    # Same id under two tenants coexist (composite PK), each private to its tenant.
    assert pgstore.count(tenant="tenant-a", url=url) >= 1
    assert pgstore.count(tenant="tenant-b", url=url) >= 1


def test_rows_without_embeddings_are_skipped_by_semantic_search(clean_offers):
    db = clean_offers
    vec = [0.0, 0.0, 1.0] + [0.0] * (pgstore.EMBED_DIM - 3)
    pgstore.upsert([{"id": "emb-yes", "title": "Has vector", "source": "BestBuy", "price": 10}], [vec], url=db)
    pgstore.upsert([{"id": "emb-no", "title": "No vector", "source": "BestBuy", "price": 10}], None, url=db)
    assert "No vector" not in {r["title"] for r in pgstore.semantic_search(vec, k=50, url=db)}


def test_offers_store_no_query_text(db):
    with psycopg.connect(db) as c:
        cols = {r[0] for r in c.execute("""select column_name from information_schema.columns
                where table_schema='dealfinder' and table_name='offers'""")}
    assert "query" not in cols


def test_upsert_never_stores_ebay_rows(clean_offers):
    db = clean_offers
    n = pgstore.upsert([{"id": "ebay-1", "title": "x", "source": "eBay:Used", "price": 5.0}], None, url=db)
    with psycopg.connect(db) as c:
        assert (n, c.execute("select count(*) from dealfinder.offers where id='ebay-1'").fetchone()[0]) == (0, 0)


def test_upsert_refreshes_fetched_at_and_keeps_provenance(clean_offers):
    db = clean_offers
    row = {"id": "bestbuy-77", "title": "TV", "source": "BestBuy", "price": 300.0, "sku": "77"}
    pgstore.upsert([{**row, "fetched_at": "2026-10-20T00:00:00Z"}], None, url=db)
    pgstore.upsert([{**row, "regular_price": 400.0, "fetched_at": "2026-10-21T00:00:00Z"}], None, url=db)
    with psycopg.connect(db) as c:
        got = c.execute("select sku, regular_price, fetched_at from dealfinder.offers where id='bestbuy-77'").fetchone()
    assert (got[0], got[1], got[2].isoformat()) == ("77", 400.0, "2026-10-21T00:00:00+00:00")
