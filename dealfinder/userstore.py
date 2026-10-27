"""Per-user private data — the consumer retention layer (watchlist, saved searches).

Where `pgstore` holds the SHARED price catalog, this holds PRIVATE, per-user data.
Same isolation primitive as the catalog: Postgres Row-Level Security, fail-closed,
enforced through `db.scoped` as the non-superuser `dealfinder_app` role. It keys on
`app.user_id`, the verified JWT `sub`, so a user only ever sees their own rows.

Prices are never taken from the client. Watching an offer copies its title, link
and current price from the server's own catalog (`dealfinder.offers`) in the same
transaction, so a client cannot set the price it is alerted on.
"""
from __future__ import annotations

from . import db

WATCH_LIMIT = 200
SAVED_SEARCH_LIMIT = 50

_WATCH_COLS = """offer_id, title, url, image_url, source, target_price, last_price,
    last_checked_at, created_at,
    (target_price IS NOT NULL AND last_price <= target_price) AS hit"""


class LimitExceeded(Exception):
    """The user already holds the maximum number of items."""


def migrate(url: str | None = None) -> list[str]:
    """Apply pending migrations (thin wrapper over `dealfinder.migrate.apply`)."""
    from . import migrate as migrations

    return migrations.apply(url)


def _lock_user(cur, user_id: str) -> None:
    """Serialize one user's writes so a count-then-insert cap can't be raced past."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (user_id,))


def add_watch(user_id: str, tenant_id: str, offer_id: str, target_price: float | None,
              url: str | None = None) -> dict:
    """Watch an offer from `tenant_id`'s catalog at the server's current price.

    Raises LookupError when the offer isn't in that tenant's catalog, and
    LimitExceeded when the user already watches WATCH_LIMIT other items.
    Re-watching an item updates its target and refreshes its price."""
    with db.scoped(user_id=user_id, tenant_id=tenant_id, url=url) as cur:
        offer = cur.execute(
            "SELECT title, url, image_url, source, price, fetched_at FROM dealfinder.offers WHERE id = %s",
            (offer_id,),
        ).fetchone()
        if offer is None:
            raise LookupError(offer_id)
        _lock_user(cur, user_id)
        watched = cur.execute("SELECT 1 FROM dealfinder.watchlist WHERE offer_id = %s", (offer_id,)).fetchone()
        if not watched:
            n = cur.execute("SELECT count(*) AS n FROM dealfinder.watchlist").fetchone()["n"]
            if n >= WATCH_LIMIT:
                raise LimitExceeded()
        return cur.execute(
            f"""
            INSERT INTO dealfinder.watchlist
                (user_id, tenant_id, offer_id, title, url, image_url, source, target_price,
                 last_price, last_checked_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, offer_id) DO UPDATE SET
                target_price=EXCLUDED.target_price, title=EXCLUDED.title, url=EXCLUDED.url,
                image_url=EXCLUDED.image_url, source=EXCLUDED.source,
                last_price=EXCLUDED.last_price, last_checked_at=EXCLUDED.last_checked_at
            RETURNING {_WATCH_COLS}
            """,
            (user_id, tenant_id, offer_id, offer["title"], offer["url"], offer["image_url"],
             offer["source"], target_price, offer["price"], offer["fetched_at"]),
        ).fetchone()


def list_watch(user_id: str, url: str | None = None) -> list[dict]:
    """The user's watched items, newest first, each with a `hit` flag."""
    with db.scoped(user_id=user_id, url=url) as cur:
        return cur.execute(
            f"SELECT {_WATCH_COLS} FROM dealfinder.watchlist ORDER BY created_at DESC"
        ).fetchall()


def remove_watch(user_id: str, offer_id: str, url: str | None = None) -> int:
    with db.scoped(user_id=user_id, url=url) as cur:
        cur.execute("DELETE FROM dealfinder.watchlist WHERE offer_id = %s", (offer_id,))
        return cur.rowcount


def add_saved_search(user_id: str, query: str, max_price: float | None,
                     url: str | None = None) -> dict:
    """Save a search for the user. Raises LimitExceeded at SAVED_SEARCH_LIMIT."""
    with db.scoped(user_id=user_id, url=url) as cur:
        _lock_user(cur, user_id)
        n = cur.execute("SELECT count(*) AS n FROM dealfinder.saved_searches").fetchone()["n"]
        if n >= SAVED_SEARCH_LIMIT:
            raise LimitExceeded()
        return cur.execute(
            """INSERT INTO dealfinder.saved_searches (user_id, query, max_price) VALUES (%s, %s, %s)
               RETURNING id, query, max_price, created_at""",
            (user_id, query, max_price),
        ).fetchone()


def list_saved_searches(user_id: str, url: str | None = None) -> list[dict]:
    """The user's saved searches, newest first."""
    with db.scoped(user_id=user_id, url=url) as cur:
        return cur.execute(
            "SELECT id, query, max_price, created_at FROM dealfinder.saved_searches ORDER BY created_at DESC"
        ).fetchall()


def remove_saved_search(user_id: str, search_id: str, url: str | None = None) -> int:
    with db.scoped(user_id=user_id, url=url) as cur:
        cur.execute("DELETE FROM dealfinder.saved_searches WHERE id = %s::uuid", (search_id,))
        return cur.rowcount
