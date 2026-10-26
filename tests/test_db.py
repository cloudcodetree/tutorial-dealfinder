"""Pooled, transaction-scoped connections (DB tests; skip without a database)."""
import pytest

from dealfinder import db as db_mod


def test_pooled_connection_does_not_leak_scope(db):
    with db_mod.scoped(user_id="user-alice", tenant_id="acme", url=db) as cur:
        cur.execute("select 1")
    with db_mod.get_pool(db).connection() as c:
        row = c.execute("""select current_user as u, current_setting('app.user_id', true) as uid,
                           current_setting('app.tenant_id', true) as tid""").fetchone()
    assert row["uid"] in (None, "") and row["tid"] in (None, "") and row["u"] != "dealfinder_app"


def test_scoped_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with db_mod.scoped(user_id="user-erin", url=db) as cur:
            cur.execute("""insert into dealfinder.watchlist (user_id, offer_id, title, last_price, last_checked_at)
                           values ('user-erin', 'x', 't', 1, now())""")
            raise RuntimeError
    with db_mod.scoped(user_id="user-erin", url=db) as cur:
        assert cur.execute("select count(*) as n from dealfinder.watchlist").fetchone()["n"] == 0


def test_scoped_sees_only_its_tenant(db):
    with db_mod.scoped(tenant_id="tenant-a", url=db) as cur:
        assert cur.execute("select current_setting('app.tenant_id', true) as t").fetchone()["t"] == "tenant-a"
