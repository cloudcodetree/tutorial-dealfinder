"""Postgres + pgvector store: persist aggregated deals and search them by meaning,
with DATABASE-ENFORCED multi-tenant isolation.

Every offer we aggregate is embedded and upserted here, so search isn't limited
to one live API call — you can semantically query everything ever seen. Each row
is owned by a `tenant_id`, and Postgres Row-Level Security (RLS) guarantees a
connection only ever sees its own tenant's rows: we `set_config('app.tenant_id', …)`
per connection and the policy filters on it. `FORCE ROW LEVEL SECURITY` makes the
policy apply even to the table owner, and `current_setting(…, true)` returns NULL
when unset — so a query that forgets to scope sees NOTHING, not everything
(fail-closed). That's the point: isolation doesn't depend on every query
remembering `WHERE tenant_id = …`; the database enforces it. See `tenancy.py`.

Connects via DATABASE_URL, so the same code runs against the local Terraform
pgvector or a managed Postgres (Supabase) — just swap the URL.
"""
from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

EMBED_DIM = 384  # bge-small-en-v1.5
DEFAULT_TENANT = "public"

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS products (
    id         text NOT NULL,
    title      text NOT NULL,
    brand      text,
    source     text NOT NULL,
    price      double precision NOT NULL,
    currency   text DEFAULT 'USD',
    url        text,
    image_url  text,
    query      text,
    embedding  vector({EMBED_DIM}),
    scraped_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS products_embedding_idx
    ON products USING hnsw (embedding vector_cosine_ops);
"""

# Multi-tenancy + Row-Level Security. Kept separate and fully idempotent because
# it also MIGRATES a table that predates tenancy (backfilling tenant_id='public'
# and widening the primary key to (tenant_id, id) so the same product id can
# belong to different tenants).
TENANCY_DDL = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'public';
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_pkey;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_tenant_pkey') THEN
    ALTER TABLE products ADD CONSTRAINT products_tenant_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS products_tenant_idx ON products (tenant_id);
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON products;
CREATE POLICY tenant_isolation ON products
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- RLS is bypassed by superusers (the default POSTGRES_USER is one), so the app
-- must run its DML as a NON-superuser role or the policy never applies. Create a
-- dedicated app role and grant it just the DML it needs; _scope() SET ROLEs to it.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dealfinder_app') THEN
    CREATE ROLE dealfinder_app NOSUPERUSER NOLOGIN;
  END IF;
END $$;
GRANT SELECT, INSERT, UPDATE, DELETE ON products TO dealfinder_app;
"""


def _url(url: str | None) -> str:
    u = url or os.getenv("DATABASE_URL")
    if not u:
        raise RuntimeError("DATABASE_URL is not set")
    return u


def _vec(emb) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"


def connect(url: str | None = None):
    return psycopg.connect(_url(url), row_factory=dict_row, connect_timeout=8)


def _scope(cur, tenant: str) -> None:
    """Bind this connection to a tenant, with RLS actually in force.

    Two steps, both required:
      1. `SET ROLE dealfinder_app` — drop from the superuser login role to the
         non-superuser app role, so the RLS policy is NOT bypassed.
      2. bind `app.tenant_id` — the policy filters every statement to `tenant`.
    Must run before any read/write; unset → the policy matches nothing (fail-closed)."""
    cur.execute("SET ROLE dealfinder_app")
    cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))


def migrate(url: str | None = None) -> None:
    with connect(url) as c:
        c.execute(DDL)
        c.execute(TENANCY_DDL)
        c.commit()


def upsert(products: list[dict], embeddings, query: str, tenant: str = DEFAULT_TENANT,
           url: str | None = None) -> int:
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, tenant)
        for p, emb in zip(products, embeddings):
            cur.execute(
                """
                INSERT INTO products
                    (tenant_id, id, title, brand, source, price, currency, url, image_url, query, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                ON CONFLICT (tenant_id, id) DO UPDATE SET
                    price=EXCLUDED.price, source=EXCLUDED.source, url=EXCLUDED.url,
                    image_url=EXCLUDED.image_url, query=EXCLUDED.query,
                    embedding=EXCLUDED.embedding, scraped_at=now()
                """,
                (tenant, p["id"], p["title"], p.get("brand"), p["source"], p["price"],
                 p.get("currency", "USD"), p.get("url"), p.get("image_url"), query, _vec(emb)),
            )
        c.commit()
        return len(products)


def semantic_search(query_embedding, k: int = 12, tenant: str = DEFAULT_TENANT,
                    url: str | None = None) -> list[dict]:
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, tenant)
        rows = cur.execute(
            """
            SELECT id, title, brand, source, price, url, image_url,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM products
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vec(query_embedding), _vec(query_embedding), k),
        ).fetchall()
    return rows


def count(tenant: str = DEFAULT_TENANT, url: str | None = None) -> int:
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, tenant)
        return cur.execute("SELECT count(*) AS n FROM products").fetchone()["n"]
