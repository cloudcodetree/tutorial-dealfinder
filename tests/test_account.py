"""Plan 5 Task 9: export and delete over the tables that exist at launch, and no cookies.

At launch (no Best Buy key) the account data is the watchlist and saved searches.
Profiles and alert history join them when alerts ship."""
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from dealfinder import serve, userstore
from dealfinder.serve import app
from tests.conftest import bearer

client = TestClient(app)

spec = importlib.util.spec_from_file_location("cookie_audit", Path("scripts/cookie_audit.py"))
cookie_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cookie_audit)


@pytest.fixture
def account_world(offers):
    db = offers
    for user, offer, query in (("user-alice", "off-1", "headphones"), ("user-bob", "off-2", "monitor")):
        userstore.add_watch(user, "public", offer, 40.0, url=db)
        userstore.add_saved_search(user, query, None, url=db)
    yield db
    for user in ("user-alice", "user-bob"):
        userstore.delete_user(user, url=db)


# ── DB ──────────────────────────────────────────────────────────────────────
def test_export_returns_every_table(account_world):
    out = userstore.export_user("user-alice", url=account_world)
    assert set(out) == {"exported_at", "watchlist", "saved_searches"}
    assert [w["offer_id"] for w in out["watchlist"]] == ["off-1"]
    assert [s["query"] for s in out["saved_searches"]] == ["headphones"]


def test_delete_account_removes_only_own_rows(account_world):
    assert userstore.delete_user("user-alice", url=account_world) == {"watchlist": 1, "saved_searches": 1}
    alice = userstore.export_user("user-alice", url=account_world)
    assert alice["watchlist"] == [] and alice["saved_searches"] == []
    bob = userstore.export_user("user-bob", url=account_world)
    assert len(bob["watchlist"]) == 1 and len(bob["saved_searches"]) == 1


def test_delete_logs_a_hash_never_the_user_id(account_world, caplog):
    caplog.set_level("INFO")
    userstore.delete_user("user-alice", url=account_world)
    logged = [json.loads(r.getMessage()) for r in caplog.records if "account_delete" in r.getMessage()]
    assert logged == [{"event": "account_delete", "user": hashlib.sha256(b"user-alice").hexdigest()[:12],
                       "counts": {"watchlist": 1, "saved_searches": 1}}]
    assert "user-alice" not in caplog.text


# ── offline ─────────────────────────────────────────────────────────────────
def test_account_routes_need_a_token():
    assert client.get("/account/export").status_code == 401 and client.delete("/account").status_code == 401


def test_export_is_a_download(mint, monkeypatch):
    monkeypatch.setattr(serve, "_DB", True)
    monkeypatch.setattr(userstore, "export_user", lambda uid, **k: {"exported_at": "t", "watchlist": [], "saved_searches": []})
    r = client.get("/account/export", headers=bearer(mint("u-1")))
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="dealfinder-export.json"'


def test_delete_says_the_sign_in_account_is_kept(mint, monkeypatch):
    monkeypatch.setattr(serve, "_DB", True)
    seen = []
    monkeypatch.setattr(userstore, "delete_user", lambda uid, **k: seen.append(uid) or {"watchlist": 1, "saved_searches": 0})
    body = client.delete("/account", headers=bearer(mint("u-1"))).json()
    assert body == {"deleted": {"watchlist": 1, "saved_searches": 0}, "sign_in_account": "kept"} and seen == ["u-1"]


def test_account_routes_say_when_the_database_is_down(mint, monkeypatch):
    monkeypatch.setattr(serve, "_DB", False)
    monkeypatch.setattr(serve, "_DB_CHECKED_AT", float("inf"))
    assert client.get("/account/export", headers=bearer(mint("u-1"))).status_code == 503


@pytest.fixture
def quiet_search(monkeypatch):
    from dealfinder import shop
    monkeypatch.setattr(serve, "_DB", False)
    monkeypatch.setattr(shop, "aggregate", lambda q: {"results": [], "sources_live": []})
    monkeypatch.setattr(shop, "ebay_box", lambda q, limit=6: {"enabled": False, "note": "", "items": []})


@pytest.mark.parametrize("path", ["/healthz", "/health", "/readyz", "/config.json", "/search?q=tv", "/lab",
                                  "/check?title=Sony%20WH-1000XM5&price=199", "/ask?q=tv"])
def test_no_backend_route_sets_cookies(path, quiet_search):
    assert "set-cookie" not in client.get(path).headers


# ── the deployed-origin audit ───────────────────────────────────────────────
@respx.mock
def test_cookie_audit_fails_on_a_tracking_cookie(capsys):
    respx.get(url__regex=r"https://deals\.example/.*").mock(return_value=httpx.Response(200, headers={"Set-Cookie": "_ga=1"}))
    assert cookie_audit.main(["https://deals.example"]) == 1
    assert "_ga" in capsys.readouterr().out


@respx.mock
def test_cookie_audit_allows_cloudflare_security_cookies():
    respx.get(url__regex=r"https://deals\.example/.*").mock(
        return_value=httpx.Response(200, headers=[("Set-Cookie", "__cf_bm=x; Path=/"), ("Set-Cookie", "cf_clearance=y")]))
    assert cookie_audit.main(["https://deals.example"]) == 0


@respx.mock
def test_cookie_audit_names_itself_and_checks_every_page():
    route = respx.get(url__regex=r"https://deals\.example/.*").mock(return_value=httpx.Response(200))
    assert cookie_audit.main(["https://deals.example"]) == 0
    paths = {c.request.url.path for c in route.calls}
    assert {"/", "/check", "/how-we-rank", "/privacy", "/lab", "/api/config.json", "/api/check"} <= paths
    assert all(not c.request.headers["user-agent"].startswith("python-httpx") for c in route.calls)


@respx.mock
def test_cookie_audit_fails_when_a_page_does_not_answer():
    respx.get(url__regex=r"https://deals\.example/.*").mock(return_value=httpx.Response(403))
    assert cookie_audit.main(["https://deals.example"]) == 1
