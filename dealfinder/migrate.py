"""Versioned SQL migrations for DealFinder's `dealfinder` schema.

Numbered files in `dealfinder/migrations/` run once each, in order, each in its
own transaction together with its row in `dealfinder.schema_migrations`. They
run only from this CLI (`python -m dealfinder.migrate`), never at import or app
startup: a web process that silently changed the schema could not be rolled back
and would race other instances. The app only asks `schema_ready()`.

DealFinder shares a Supabase project with cloudcodetree.com, so every migration
stays inside the `dealfinder` schema and never touches another schema's tables.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS dealfinder;
CREATE TABLE IF NOT EXISTS dealfinder.schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def _url(url: str | None) -> str:
    u = url or os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not u:
        raise RuntimeError("no database URL: set MIGRATION_DATABASE_URL or DATABASE_URL")
    return u


def _files() -> list[str]:
    return sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))


def _applied(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT filename FROM dealfinder.schema_migrations")}


def pending(url: str | None = None) -> list[str]:
    """Migration files not yet recorded as applied, in run order.

    A database with no log table has applied nothing, so every file is pending."""
    with psycopg.connect(_url(url), connect_timeout=8) as conn:
        try:
            done = _applied(conn)
        except psycopg.errors.UndefinedTable:
            done = set()
    return [f for f in _files() if f not in done]


def apply(url: str | None = None) -> list[str]:
    """Apply every pending migration; return the filenames applied this run."""
    applied: list[str] = []
    with psycopg.connect(_url(url), connect_timeout=8) as conn:
        conn.execute(_BOOTSTRAP)
        conn.commit()
        done = _applied(conn)
        for name in _files():
            if name in done:
                continue
            with conn.transaction():
                conn.execute((MIGRATIONS_DIR / name).read_text())
                conn.execute("INSERT INTO dealfinder.schema_migrations (filename) VALUES (%s)", (name,))
            applied.append(name)
    return applied


def schema_ready(url: str | None = None) -> bool:
    """True when the database is reachable and has no pending migration.

    Never raises: an unreachable database or a missing log table reads as not ready."""
    try:
        return pending(url) == []
    except Exception:
        return False


if __name__ == "__main__":
    ran = apply()
    print("\n".join(f"applied {f}" for f in ran) if ran else "up to date")
