"""Multi-tenancy — tenant RESOLUTION (offline). The ENFORCEMENT half (RLS) is
proven in tests/test_pgstore.py, which runs when a DB is reachable.

Same offline ES256 scheme as test_auth (the `mint` fixture): mint tokens locally,
exercise the real dependency, never touch the network.
"""
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dealfinder.tenancy import (
    Principal,
    _tenant_from_claims,
    current_principal,
    require_account,
)
from tests.conftest import bearer

app = FastAPI()


@app.get("/whoami")
def whoami(who: Principal = Depends(current_principal)):
    return {"tenant": who.tenant_id, "user": who.user_id, "role": who.role}


@app.get("/account")
def account(who: Principal = Depends(require_account)):
    return {"user": who.user_id}


client = TestClient(app)


def test_tenant_from_claims_reads_common_shapes():
    assert _tenant_from_claims({"app_metadata": {"tenant": "acme"}}) == "acme"
    assert _tenant_from_claims({"app_metadata": {"tenant_id": "acme2"}}) == "acme2"
    assert _tenant_from_claims({"org_id": "org-9"}) == "org-9"
    assert _tenant_from_claims({"tenant": "t1"}) == "t1"
    assert _tenant_from_claims({}) is None


def test_no_token_is_public_anonymous():
    assert client.get("/whoami").json() == {"tenant": "public", "user": None, "role": "anonymous"}


def test_identity_headers_are_ignored():
    r = client.get("/whoami", headers={"X-User-Id": "alice", "X-Tenant-Id": "acme"})
    assert r.json() == {"tenant": "public", "user": None, "role": "anonymous"}


def test_token_tenant_claim_scopes(mint):
    r = client.get("/whoami", headers=bearer(mint("u-1", app_metadata={"tenant": "acme", "plan": "pro"})))
    assert r.json() == {"tenant": "acme", "user": "u-1", "role": "pro"}


def test_account_needs_a_token(mint):
    assert client.get("/account").status_code == 401
    assert client.get("/account", headers=bearer(mint("u-2"))).json() == {"user": "u-2"}


def test_real_app_watchlist_rejects_header_identity():
    from dealfinder.serve import app as real
    assert TestClient(real).get("/watchlist", headers={"X-User-Id": "alice"}).status_code == 401


def test_search_still_works_when_auth_is_down(monkeypatch, stub_sources):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    from dealfinder.serve import app as real
    assert TestClient(real).get("/ranked", params={"q": "headphones"}).status_code == 200
