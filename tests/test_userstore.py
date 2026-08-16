"""Per-user watchlist isolation (RLS) — runs when a DB is reachable, skips otherwise
(keeps the suite offline-green in CI; real when DATABASE_URL points at pgvector)."""
import os

import pytest

from dealfinder import userstore


def _db():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        userstore.migrate(url)
    except Exception as e:
        pytest.skip(f"db unavailable: {e}")
    return url


def test_watchlist_is_private_per_user():
    url = _db()
    # Same item id under two users — the composite key + RLS keep them separate.
    userstore.add_watch("user-alice", {"id": "w-iso", "title": "Alice Item",
                                       "last_price": 50.0, "target_price": 40.0}, url=url)
    userstore.add_watch("user-bob", {"id": "w-iso", "title": "Bob Item",
                                     "last_price": 9.0, "target_price": 40.0}, url=url)
    try:
        alice = userstore.list_watch("user-alice", url=url)
        bob = userstore.list_watch("user-bob", url=url)
        a_titles = {r["title"] for r in alice}
        b_titles = {r["title"] for r in bob}
        assert "Alice Item" in a_titles and "Bob Item" not in a_titles
        assert "Bob Item" in b_titles and "Alice Item" not in b_titles

        # price-drop `hit`: bob's $9 <= $40 target is a hit; alice's $50 > $40 isn't.
        assert next(r for r in bob if r["title"] == "Bob Item")["hit"] is True
        assert next(r for r in alice if r["title"] == "Alice Item")["hit"] is False

        # a user can't delete another user's row (RLS scopes the DELETE).
        assert userstore.remove_watch("user-bob", "w-iso", url=url) == 1
        assert "Bob Item" not in {r["title"] for r in userstore.list_watch("user-bob", url=url)}
        assert "Alice Item" in {r["title"] for r in userstore.list_watch("user-alice", url=url)}
    finally:
        userstore.remove_watch("user-alice", "w-iso", url=url)
        userstore.remove_watch("user-bob", "w-iso", url=url)
