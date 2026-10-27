"""Pooled Postgres connections where every query runs inside one scoped transaction.

`scoped()` is the only way request-path code reaches the database. Each call
checks a connection out of the pool, opens ONE transaction, and inside it:

  1. `SET LOCAL ROLE dealfinder_app` drops to the non-superuser app role, so the
     Row-Level Security policies apply (superusers bypass them);
  2. `SET LOCAL search_path` points unqualified names at the `dealfinder` schema;
  3. `set_config('app.tenant_id' / 'app.user_id', …, true)` binds the scope the
     policies filter on.

All three are transaction-local, so they end at COMMIT or ROLLBACK. A pooled
connection handed to the next request carries no previous user's role or id.
Session-level settings would leak across requests and are never used.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}
_lock = threading.Lock()

# How long a request waits for a pooled connection before giving up. Short, so a
# database outage costs a request seconds, not the pool's 30-second default.
_CHECKOUT_TIMEOUT_S = float(os.getenv("DB_CHECKOUT_TIMEOUT_S", "3"))


def _url(url: str | None) -> str:
    u = url or os.getenv("DATABASE_URL")
    if not u:
        raise RuntimeError("DATABASE_URL is not set")
    return u


def get_pool(url: str | None = None) -> ConnectionPool:
    """One pool per database URL. `prepare_threshold=None` keeps psycopg from
    preparing statements, which the Supabase transaction pooler cannot route."""
    u = _url(url)
    with _lock:
        if u not in _pools:
            _pools[u] = ConnectionPool(
                u, min_size=1, max_size=int(os.getenv("DB_POOL_MAX", "5")), open=True,
                kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 8},
            )
        return _pools[u]


@contextmanager
def scoped(*, user_id: str | None = None, tenant_id: str = "public",
           url: str | None = None) -> Iterator[psycopg.Cursor]:
    """One transaction as `dealfinder_app`, scoped to a tenant and (optionally) a user.

    Commits on a clean exit, rolls back on an exception."""
    with get_pool(url).connection(timeout=_CHECKOUT_TIMEOUT_S) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE dealfinder_app")
        cur.execute("SET LOCAL search_path = dealfinder, extensions, public")
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true)",
                    (tenant_id, user_id or ""))
        yield cur


@contextmanager
def job_scope(*, url: str | None = None) -> Iterator[psycopg.Cursor]:
    """One transaction as `dealfinder_job`, for scheduled jobs that work across users.

    The role's `job_all` policies grant every row of every dealfinder table, so a
    job can purge or re-price all users' rows. It is never used on the request
    path. Both settings are transaction-local, like `scoped()`."""
    with get_pool(url).connection(timeout=_CHECKOUT_TIMEOUT_S) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE dealfinder_job")
        cur.execute("SET LOCAL search_path = dealfinder, extensions, public")
        yield cur


def ping(url: str | None = None) -> bool:
    """True when the database answers within a few seconds."""
    try:
        with get_pool(url).connection(timeout=_CHECKOUT_TIMEOUT_S) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def schema_current(url: str | None = None) -> bool:
    """True when every migration file is recorded as applied, checked through the pool.

    The web process uses this instead of `migrate.schema_ready`, which opens its
    own connection and may use the migration URL."""
    from . import migrate

    try:
        with get_pool(url).connection(timeout=_CHECKOUT_TIMEOUT_S) as conn:
            done = {r["filename"] for r in conn.execute("SELECT filename FROM dealfinder.schema_migrations")}
        return set(migrate._files()) <= done
    except Exception:
        return False
