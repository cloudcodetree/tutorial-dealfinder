"""Postgres + pgvector store: persist aggregated deals and search them by meaning.

Every offer we aggregate is embedded and upserted here, so search isn't limited
to one live API call — you can semantically query everything ever seen
("comfy gym earbuds" finds stored earbuds even if they were scraped under a
different term). Connects via DATABASE_URL, so the same code runs against the
local Terraform pgvector or a managed Postgres (Supabase) — just swap the URL.
"""
from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

EMBED_DIM = 384  # bge-small-en-v1.5

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS products (
    id         text PRIMARY KEY,
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


def _url(url: str | None) -> str:
    u = url or os.getenv("DATABASE_URL")
    if not u:
        raise RuntimeError("DATABASE_URL is not set")
    return u


def _vec(emb) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"


def connect(url: str | None = None):
    return psycopg.connect(_url(url), row_factory=dict_row, connect_timeout=8)


def migrate(url: str | None = None) -> None:
    with connect(url) as c:
        c.execute(DDL)
        c.commit()


def upsert(products: list[dict], embeddings, query: str, url: str | None = None) -> int:
    with connect(url) as c, c.cursor() as cur:
        for p, emb in zip(products, embeddings):
            cur.execute(
                """
                INSERT INTO products
                    (id, title, brand, source, price, currency, url, image_url, query, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                ON CONFLICT (id) DO UPDATE SET
                    price=EXCLUDED.price, source=EXCLUDED.source, url=EXCLUDED.url,
                    image_url=EXCLUDED.image_url, query=EXCLUDED.query,
                    embedding=EXCLUDED.embedding, scraped_at=now()
                """,
                (p["id"], p["title"], p.get("brand"), p["source"], p["price"],
                 p.get("currency", "USD"), p.get("url"), p.get("image_url"), query, _vec(emb)),
            )
        c.commit()
        return len(products)


def semantic_search(query_embedding, k: int = 12, url: str | None = None) -> list[dict]:
    with connect(url) as c:
        rows = c.execute(
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


def count(url: str | None = None) -> int:
    with connect(url) as c:
        return c.execute("SELECT count(*) AS n FROM products").fetchone()["n"]
