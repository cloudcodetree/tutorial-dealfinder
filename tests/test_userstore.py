"""Per-user watchlist: server-side prices and RLS isolation (DB tests; skip without a database)."""
import psycopg
import pytest

from dealfinder import pgstore, userstore

_IDS = ("off-1", "off-2", "acme-1")


@pytest.fixture
def offers(db):
    """Three catalog offers (two public, one in tenant acme); removes everything the tests made."""
    pgstore.upsert([{"id": "off-1", "title": "Anker Soundcore Q20i", "source": "S", "price": 44.99},
                    {"id": "off-2", "title": "Bose QuietComfort 45", "source": "S", "price": 46.00}],
                   None, tenant="public", url=db)
    pgstore.upsert([{"id": "acme-1", "title": "Acme Only", "source": "S", "price": 10.0}],
                   None, tenant="acme", url=db)
    yield db
    with psycopg.connect(db) as c:
        c.execute("delete from dealfinder.watchlist where offer_id = any(%s)", (list(_IDS) + ["nope"],))
        c.execute("delete from dealfinder.offers where id = any(%s)", (list(_IDS),))


def test_watch_uses_server_price(db, offers):
    row = userstore.add_watch("user-alice", "public", "off-1", target_price=40.0, url=db)
    assert row["last_price"] == 44.99 and row["title"] == "Anker Soundcore Q20i"


def test_watch_unknown_offer(db, offers):
    with pytest.raises(LookupError):
        userstore.add_watch("user-alice", "public", "nope", None, url=db)


def test_watch_offer_from_other_tenant_is_not_found(db, offers):
    with pytest.raises(LookupError):
        userstore.add_watch("user-alice", "public", "acme-1", None, url=db)


def test_watchlist_is_private_per_user(db, offers):
    userstore.add_watch("user-alice", "public", "off-1", 40.0, url=db)
    userstore.add_watch("user-bob", "public", "off-2", 50.0, url=db)
    assert {r["offer_id"] for r in userstore.list_watch("user-alice", url=db)} == {"off-1"}
    assert {r["offer_id"] for r in userstore.list_watch("user-bob", url=db)} == {"off-2"}
    assert userstore.remove_watch("user-bob", "off-1", url=db) == 0


def test_hit_flag(db, offers):
    userstore.add_watch("user-carol", "public", "off-2", target_price=50.0, url=db)
    assert userstore.list_watch("user-carol", url=db)[0]["hit"] is True
