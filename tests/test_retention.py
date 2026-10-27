"""Best Buy rows are gone before 72 hours; unstorable rows are gone at any age (DB tests)."""
import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from dealfinder import db as db_mod
from dealfinder import retention

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
_OFFERS = ("ret-bb-fresh", "ret-bb-old", "ret-ebay", "ret-walmart")
_OWNERS = ("ret-alice", "ret-bob")


def offer_ids(url):
    with db_mod.job_scope(url=url) as cur:
        return {r["id"] for r in cur.execute("select id from dealfinder.offers where id = any(%s)", (list(_OFFERS),))}


def watch_owners(url):
    with db_mod.job_scope(url=url) as cur:
        return {r["user_id"] for r in cur.execute(
            "select user_id from dealfinder.watchlist where user_id = any(%s)", (list(_OWNERS),))}


@pytest.fixture
def clean(db):
    yield db
    with psycopg.connect(db) as c:
        c.execute("delete from dealfinder.watchlist where user_id = any(%s)", (list(_OWNERS),))
        c.execute("delete from dealfinder.offers where id = any(%s)", (list(_OFFERS),))


def test_purge_removes_rows_past_policy_age(clean):
    db = clean
    retention.purge_expired(now=NOW, url=db)   # clear rows other tests left behind, so counts are exact
    with db_mod.job_scope(url=db) as cur:
        for oid, hours in (("ret-bb-fresh", 46), ("ret-bb-old", 48)):
            cur.execute("""insert into dealfinder.offers (tenant_id, id, title, source, price, fetched_at)
                           values ('public', %s, 'TV', 'BestBuy', 300, %s)""", (oid, NOW - timedelta(hours=hours)))
        for owner, oid, hours in (("ret-alice", "ret-bb-fresh", 46), ("ret-bob", "ret-bb-old", 48)):
            cur.execute("""insert into dealfinder.watchlist (user_id, offer_id, title, source, last_price, last_checked_at)
                           values (%s, %s, 'TV', 'BestBuy', 300, %s)""", (owner, oid, NOW - timedelta(hours=hours)))
    assert retention.purge_expired(now=NOW, url=db) == {"offers": 1, "watchlist": 1}
    assert offer_ids(db) & {"ret-bb-fresh", "ret-bb-old"} == {"ret-bb-fresh"}
    assert watch_owners(db) & {"ret-alice", "ret-bob"} == {"ret-alice"}
    assert retention.purge_expired(now=NOW, url=db) == {"offers": 0, "watchlist": 0}


def test_purge_deletes_unstorable_rows_of_any_age(clean):
    db = clean
    retention.purge_expired(now=NOW, url=db)
    with psycopg.connect(db) as c:   # superuser inserts, bypassing the upsert guard
        for oid, source in (("ret-ebay", "eBay:Used"), ("ret-walmart", "Walmart")):
            c.execute("""insert into dealfinder.offers (tenant_id, id, title, source, price, fetched_at)
                         values ('public', %s, 'Old', %s, 9, %s)""", (oid, source, NOW - timedelta(minutes=1)))
    assert retention.purge_expired(now=NOW, url=db)["offers"] == 2
    assert offer_ids(db) == set()


def test_purge_cli_prints_counts(clean, capsys, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", clean)
    assert retention.main([]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"offers", "watchlist"}


def test_purge_cli_reports_a_database_error(monkeypatch, capsys):
    monkeypatch.setattr(retention, "purge_expired", lambda *a, **k: (_ for _ in ()).throw(psycopg.OperationalError("down")))
    assert retention.main([]) == 1
    assert "down" in capsys.readouterr().err


def test_best_buy_cutoff_survives_one_missed_run():
    # The purge runs every 12 h. Even if one run fails, the next one must still
    # delete a Best Buy row before it is 72 h old: cut-off + 2 × 12 h < 72 h.
    from dealfinder.licensing import POLICIES
    cutoff = POLICIES["BestBuy"].max_age_s - retention.RETENTION_MARGIN_S
    assert cutoff == 47 * 3600 and cutoff + 2 * 12 * 3600 < 72 * 3600
