"""Persist the normalized catalog to SQLite (one row per product, JSON payload)."""

from __future__ import annotations

import sqlite3

from dealfinder.schema import Product


def save(products: list[Product], db_path: str) -> int:
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, json TEXT)")
    con.executemany(
        "INSERT OR REPLACE INTO products VALUES (?, ?)",
        [(p.id, p.model_dump_json()) for p in products],
    )
    con.commit()
    n = con.total_changes
    con.close()
    return n


def load(db_path: str) -> list[Product]:
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT json FROM products").fetchall()
    con.close()
    return [Product.model_validate_json(r[0]) for r in rows]
