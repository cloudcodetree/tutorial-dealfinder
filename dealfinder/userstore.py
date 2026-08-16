"""Per-user private data — the consumer retention layer (watchlist + price alerts).

Where `pgstore` holds the SHARED price catalog (everyone's searches feed the moat),
this holds PRIVATE, per-user data. Same isolation primitive as the catalog — Postgres
Row-Level Security, fail-closed, enforced via the non-superuser `dealfinder_app` role —
but keyed on `app.user_id` (the person) instead of `app.tenant_id`. A user only ever
sees their own watchlist; the database guarantees it.
"""
from __future__ import annotations

from .pgstore import connect  # reuse the same DATABASE_URL connection helper

WATCHLIST_DDL = """
CREATE TABLE IF NOT EXISTS watchlist (
    user_id      text NOT NULL,
    id           text NOT NULL,
    title        text NOT NULL,
    url          text,
    image_url    text,
    source       text,
    target_price double precision,
    last_price   double precision,
    created_at   timestamptz DEFAULT now(),
    PRIMARY KEY (user_id, id)
);
-- The app role may already exist (pgstore.migrate creates it); ensure it anyway so
-- userstore.migrate is order-independent.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dealfinder_app') THEN
    CREATE ROLE dealfinder_app NOSUPERUSER NOLOGIN;
  END IF;
END $$;
ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS watchlist_owner ON watchlist;
CREATE POLICY watchlist_owner ON watchlist
    USING (user_id = current_setting('app.user_id', true))
    WITH CHECK (user_id = current_setting('app.user_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON watchlist TO dealfinder_app;
"""


def migrate(url: str | None = None) -> None:
    with connect(url) as c:
        c.execute(WATCHLIST_DDL)
        c.commit()


def _scope(cur, user_id: str) -> None:
    """Drop to the non-superuser app role and bind this connection to one user, so
    RLS filters every statement to their rows (unset → nothing; fail-closed)."""
    cur.execute("SET ROLE dealfinder_app")
    cur.execute("SELECT set_config('app.user_id', %s, false)", (user_id,))


def add_watch(user_id: str, item: dict, url: str | None = None) -> dict:
    """Add (or update) a watched item for `user_id`. `item` carries id/title and an
    optional target_price + the price seen now (last_price)."""
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, user_id)
        cur.execute(
            """
            INSERT INTO watchlist (user_id, id, title, url, image_url, source, target_price, last_price)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, id) DO UPDATE SET
                target_price=EXCLUDED.target_price, last_price=EXCLUDED.last_price,
                title=EXCLUDED.title, url=EXCLUDED.url, image_url=EXCLUDED.image_url,
                source=EXCLUDED.source
            RETURNING id, title, url, image_url, source, target_price, last_price, created_at
            """,
            (user_id, item["id"], item["title"], item.get("url"), item.get("image_url"),
             item.get("source"), item.get("target_price"), item.get("last_price")),
        )
        row = cur.fetchone()
        c.commit()
        return row


def list_watch(user_id: str, url: str | None = None) -> list[dict]:
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, user_id)
        rows = cur.execute(
            """
            SELECT id, title, url, image_url, source, target_price, last_price, created_at,
                   (target_price IS NOT NULL AND last_price IS NOT NULL AND last_price <= target_price) AS hit
            FROM watchlist ORDER BY created_at DESC
            """
        ).fetchall()
    return rows


def remove_watch(user_id: str, item_id: str, url: str | None = None) -> int:
    with connect(url) as c, c.cursor() as cur:
        _scope(cur, user_id)
        cur.execute("DELETE FROM watchlist WHERE id = %s", (item_id,))
        n = cur.rowcount
        c.commit()
        return n
