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


@pytest.fixture
def clean_saved(db):
    yield db
    with psycopg.connect(db) as c:
        c.execute("delete from dealfinder.saved_searches where user_id in ('user-alice', 'user-bob', 'user-dave')")


def test_saved_searches_private_per_user(db, clean_saved):
    a = userstore.add_saved_search("user-alice", "noise cancelling headphones", 150.0, url=db)
    userstore.add_saved_search("user-bob", "mechanical keyboard", None, url=db)
    assert [s["query"] for s in userstore.list_saved_searches("user-alice", url=db)] == ["noise cancelling headphones"]
    assert userstore.remove_saved_search("user-bob", str(a["id"]), url=db) == 0


def test_saved_search_cap(db, clean_saved):
    for i in range(50):
        userstore.add_saved_search("user-dave", f"q{i}", None, url=db)
    with pytest.raises(userstore.LimitExceeded):
        userstore.add_saved_search("user-dave", "one too many", None, url=db)


def test_database_rejects_non_finite_prices(db, offers, clean_saved):
    with pytest.raises(psycopg.errors.CheckViolation):
        userstore.add_watch("user-alice", "public", "off-1", target_price=float("inf"), url=db)
    with pytest.raises(psycopg.errors.CheckViolation):
        userstore.add_saved_search("user-alice", "ok", float("nan"), url=db)
