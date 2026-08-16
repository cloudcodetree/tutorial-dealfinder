"""Multi-tenancy — tenant RESOLUTION (offline). The ENFORCEMENT half (RLS) is
proven in tests/test_pgstore.py, which runs when a DB is reachable.

Same throwaway-HS256 scheme as test_auth: mint tokens locally, exercise the real
dependency, never touch the network.
"""
import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dealfinder.tenancy import (
    DEFAULT_TENANT,
    Principal,
    _tenant_from_claims,
    current_principal,
    require_account,
)

SECRET = "test-jwt-secret-not-real"


def _token(tenant=None, sub="user-1", role="pro"):
    now = int(time.time())
    app_meta = {"plan": role}
    if tenant is not None:
        app_meta["tenant"] = tenant
    claims = {"sub": sub, "aud": "authenticated", "iat": now, "exp": now + 3600,
              "app_metadata": app_meta}
    return jwt.encode(claims, SECRET, algorithm="HS256")


app = FastAPI()


@app.get("/whoami")
def whoami(who: Principal = Depends(current_principal)):
    return {"tenant": who.tenant_id, "user": who.user_id, "role": who.role}


@app.get("/account")
def account(who: Principal = Depends(require_account)):
    return {"user": who.user_id}


client = TestClient(app)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)


def test_tenant_from_claims_reads_common_shapes():
    assert _tenant_from_claims({"app_metadata": {"tenant": "acme"}}) == "acme"
    assert _tenant_from_claims({"app_metadata": {"tenant_id": "acme2"}}) == "acme2"
    assert _tenant_from_claims({"org_id": "org-9"}) == "org-9"
    assert _tenant_from_claims({"tenant": "t1"}) == "t1"
    assert _tenant_from_claims({}) is None


def test_anonymous_defaults_to_public_tenant():
    r = client.get("/whoami").json()
    assert r["tenant"] == DEFAULT_TENANT and r["user"] is None and r["role"] == "anonymous"


def test_dev_header_resolves_tenant_without_a_token():
    r = client.get("/whoami", headers={"X-Tenant-Id": "acme-co"}).json()
    assert r["tenant"] == "acme-co" and r["role"] == "anonymous"


def test_jwt_tenant_claim_wins_and_carries_identity():
    tok = _token(tenant="tenant-from-jwt", sub="u-42", role="pro")
    r = client.get("/whoami", headers={"Authorization": f"Bearer {tok}"}).json()
    assert r["tenant"] == "tenant-from-jwt" and r["user"] == "u-42" and r["role"] == "pro"


def test_jwt_without_tenant_claim_falls_back_to_header_then_default():
    tok = _token(tenant=None, sub="u-7")
    assert client.get("/whoami", headers={"Authorization": f"Bearer {tok}"}).json()["tenant"] == DEFAULT_TENANT
    both = client.get("/whoami", headers={"Authorization": f"Bearer {tok}", "X-Tenant-Id": "h-tenant"}).json()
    assert both["tenant"] == "h-tenant" and both["user"] == "u-7"


def test_x_user_id_header_identifies_a_dev_user():
    r = client.get("/whoami", headers={"X-User-Id": "dev-user-1"}).json()
    assert r["user"] == "dev-user-1" and r["role"] == "user"


def test_require_account_gates_anonymous_but_allows_identified():
    assert client.get("/account").status_code == 401                     # anonymous → blocked
    r = client.get("/account", headers={"X-User-Id": "dev-user-1"})
    assert r.status_code == 200 and r.json()["user"] == "dev-user-1"     # dev header → allowed
    tok = _token(tenant=None, sub="u-9")
    assert client.get("/account", headers={"Authorization": f"Bearer {tok}"}).json()["user"] == "u-9"
