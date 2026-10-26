"""Versioned migrations into the `dealfinder` schema (Plan 1, Task 1).

DB tests use the shared `db` fixture (skips without a reachable DATABASE_URL).
The two offline tests pin that serving the app never runs a migration."""
from pathlib import Path

import psycopg
import pytest

from dealfinder import migrate, serve


def test_apply_is_idempotent(db):
    url = db
    migrate.apply(url)                      # first run may or may not apply
    assert migrate.apply(url) == []         # second run applies nothing
    assert migrate.pending(url) == []
    assert migrate.schema_ready(url) is True


def test_tables_live_in_dealfinder_schema(db):
    url = db
    with psycopg.connect(url) as c:
        names = {r[0] for r in c.execute(
            "select table_name from information_schema.tables where table_schema='dealfinder'")}
    assert {"offers", "watchlist", "schema_migrations"} <= names


def test_app_role_cannot_bypass_rls(db):
    url = db
    with psycopg.connect(url) as c:
        row = c.execute("select rolsuper, rolbypassrls from pg_roles where rolname='dealfinder_app'").fetchone()
    assert row == (False, False)


def test_rls_is_forced_on_every_table(db):
    url = db
    with psycopg.connect(url) as c:
        rows = c.execute("""select relname, relrowsecurity, relforcerowsecurity from pg_class
            join pg_namespace n on n.oid = relnamespace
            where nspname='dealfinder' and relname in ('offers','watchlist')""").fetchall()
    assert sorted(rows) == [("offers", True, True), ("watchlist", True, True)]


def test_db_ready_never_migrates(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:9/none")
    monkeypatch.setattr(migrate, "apply", lambda *a, **k: pytest.fail("serve must not migrate"))
    monkeypatch.setattr(migrate, "schema_ready", lambda *a, **k: False)
    assert serve._db_ready() is False


def test_serve_source_has_no_migration_calls():
    src = Path(serve.__file__).read_text()
    assert "migrate.apply" not in src and "pgstore.migrate" not in src and "userstore.migrate" not in src
