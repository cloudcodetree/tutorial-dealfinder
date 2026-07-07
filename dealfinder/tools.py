"""Tools the agent can call. Each is a plain function — the agent doesn't care
whether the "reasoning" picking them is scripted or an LLM.

nl_to_sql is the text-to-SQL tool (rule-based here so it's deterministic and
offline; an LLM would generate the same kind of WHERE clause).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .extract import KNOWN_TENT_BRANDS
from .schema import Product

CATALOG = Path("data/sample/catalog.json")


def nl_to_sql(question: str, table: str = "catalog") -> str:
    clauses: list[str] = []
    if m := re.search(r"under \$?(\d+)", question, re.I):
        clauses.append(f"price < {m.group(1)}")
    if m := re.search(r"over \$?(\d+)", question, re.I):
        clauses.append(f"price > {m.group(1)}")
    if m := re.search(r"(\d+)\s*-?\s*person|sleeps?\s+(\d+)", question, re.I):
        clauses.append(f"capacity = {m.group(1) or m.group(2)}")
    brand = next((b for b in KNOWN_TENT_BRANDS if b.lower() in question.lower()), None)
    if brand:
        clauses.append(f"brand = '{brand}'")
    where = " AND ".join(clauses) if clauses else "1=1"
    return f"SELECT * FROM {table} WHERE {where}"


def load_catalog(path: Path = CATALOG) -> list[Product]:
    return [Product.model_validate(r) for r in json.loads(path.read_text())]


def build_db(products: list[Product]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE catalog (id TEXT, title TEXT, brand TEXT, price REAL, "
        "capacity INT, weight REAL, season INT)"
    )
    con.executemany(
        "INSERT INTO catalog VALUES (?,?,?,?,?,?,?)",
        [
            (p.id, p.title, p.brand, p.price,
             int(p.specs.get("capacity", 0)), float(p.specs.get("weight_kg", 0)),
             int(p.specs.get("season", 0)))
            for p in products
        ],
    )
    return con


def run_sql(con: sqlite3.Connection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
