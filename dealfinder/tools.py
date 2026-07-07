"""Tools the agent can call. Each is a plain function — the agent doesn't care
whether the "reasoning" picking them is scripted or an LLM.

The catalog is the real frozen snapshot (270 electronics listings). ``nl_to_sql``
is the text-to-SQL tool (rule-based here so it's deterministic and offline; an LLM
would generate the same kind of WHERE clause). Because the raw ``brand`` field is
the retailer in most rows, brand filtering keys off the *title-extracted*
manufacturer, matched with a LIKE against the title.
"""
from __future__ import annotations

import re
import sqlite3

from .extract import KNOWN_CATEGORIES, guess_category
from .features import _BRAND_LIST, title_brand
from .schema import Product
from .snapshot import load_products

_CONDITION_WORDS = {"new": "new", "refurb": "refurb", "refurbished": "refurb",
                    "renewed": "refurb", "open box": "refurb", "used": "used"}


def nl_to_sql(question: str, table: str = "catalog") -> str:
    """Translate a natural-language shopping request into a SQL query.

    Recognizes price bounds, a category, a condition, and a brand (matched on the
    title, since the raw ``brand`` column holds the retailer).
    """
    q = question.lower()
    clauses: list[str] = []
    if m := re.search(r"under \$?(\d+)", q):
        clauses.append(f"price < {m.group(1)}")
    if m := re.search(r"over \$?(\d+)", q):
        clauses.append(f"price > {m.group(1)}")
    # Category: an explicit category word, else infer it from the wording
    # ("noise cancelling headphones" → audio) via the same hints the extractor uses.
    category = next((c for c in KNOWN_CATEGORIES if c != "misc" and c in q), None) \
        or guess_category(question)
    if category:
        clauses.append(f"category = '{category}'")
    condition = next((v for k, v in _CONDITION_WORDS.items() if k in q), None)
    if condition:
        clauses.append(f"condition = '{condition}'")
    brand = title_brand(question)  # e.g. "Sony", "Anker" — the true manufacturer
    if brand and brand in _BRAND_LIST:
        clauses.append(f"title LIKE '%{brand}%'")
    # A product-type keyword narrows within a broad category (e.g. "headphone"
    # keeps headphones out of the wider "audio" bucket of speakers/earbuds).
    for kw in ("headphone", "earbud", "speaker", "soundbar", "keyboard", "mouse",
               "monitor", "laptop", "tablet", "watch", "webcam"):
        if kw in q:
            clauses.append(f"title LIKE '%{kw}%'")
            break
    where = " AND ".join(clauses) if clauses else "1=1"
    return f"SELECT * FROM {table} WHERE {where}"


def load_catalog(path: str | None = None) -> list[Product]:
    """The real snapshot catalog as normalized ``Product`` rows."""
    return load_products(path)


def build_db(products: list[Product]) -> sqlite3.Connection:
    """An in-memory SQLite table over the electronics catalog for text-to-SQL."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE catalog (id TEXT, title TEXT, brand TEXT, category TEXT, "
        "price REAL, condition TEXT, source TEXT)"
    )
    con.executemany(
        "INSERT INTO catalog VALUES (?,?,?,?,?,?,?)",
        [(p.id, p.title, p.brand, p.category, p.price, p.condition, p.source) for p in products],
    )
    return con


def run_sql(con: sqlite3.Connection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
