"""Postgres + pgvector store: persist aggregated deals and search them by meaning,
with DATABASE-ENFORCED multi-tenant isolation.

Offers live in `dealfinder.offers` (created by `dealfinder/migrations/`). Each row
is owned by a `tenant_id`, and Postgres Row-Level Security guarantees a query only
ever sees its own tenant's rows. Every call goes through `db.scoped`, which runs
one transaction as the non-superuser `dealfinder_app` role with a
transaction-local `app.tenant_id`, so RLS applies and nothing leaks to the next
pooled request. `current_setting(…, true)` returns NULL when unset, so a query
that forgot to scope sees NOTHING (fail-closed). See `tenancy.py` and `db.py`.

The embedding is optional: an offer can be stored before it is embedded (for
example so a shopper can watch it), and semantic search skips rows without one.
No search query text is stored.

Connects via DATABASE_URL, so the same code runs against the local pgvector or a
managed Postgres (Supabase, through its pooler).
"""
from __future__ import annotations

from . import db

EMBED_DIM = 384  # bge-small-en-v1.5
DEFAULT_TENANT = "public"


def _vec(emb) -> str | None:
    return None if emb is None else "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"


def migrate(url: str | None = None) -> list[str]:
    """Apply pending migrations (thin wrapper over `dealfinder.migrate.apply`)."""
    from . import migrate as migrations

    return migrations.apply(url)


def upsert(products: list[dict], embeddings: list | None, tenant: str = DEFAULT_TENANT,
           url: str | None = None) -> int:
    """Insert or refresh offers for `tenant`. A `None` embedding keeps the stored one."""
    embs = embeddings if embeddings is not None else [None] * len(products)
    with db.scoped(tenant_id=tenant, url=url) as cur:
        for p, emb in zip(products, embs):
            cur.execute(
                """
                INSERT INTO dealfinder.offers
                    (tenant_id, id, title, brand, source, price, currency, url, image_url, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                ON CONFLICT (tenant_id, id) DO UPDATE SET
                    title=EXCLUDED.title, brand=EXCLUDED.brand, price=EXCLUDED.price,
                    source=EXCLUDED.source, currency=EXCLUDED.currency, url=EXCLUDED.url,
                    image_url=EXCLUDED.image_url,
                    embedding=COALESCE(EXCLUDED.embedding, offers.embedding),
                    fetched_at=now()
                """,
                (tenant, p["id"], p["title"], p.get("brand"), p["source"], p["price"],
                 p.get("currency") or "USD", p.get("url"), p.get("image_url"), _vec(emb)),
            )
    return len(products)


def semantic_search(query_embedding, k: int = 12, tenant: str = DEFAULT_TENANT,
                    url: str | None = None) -> list[dict]:
    with db.scoped(tenant_id=tenant, url=url) as cur:
        return cur.execute(
            """
            SELECT id, title, brand, source, price, url, image_url,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM dealfinder.offers
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vec(query_embedding), _vec(query_embedding), k),
        ).fetchall()


def count(tenant: str = DEFAULT_TENANT, url: str | None = None) -> int:
    with db.scoped(tenant_id=tenant, url=url) as cur:
        return cur.execute("SELECT count(*) AS n FROM dealfinder.offers").fetchone()["n"]
