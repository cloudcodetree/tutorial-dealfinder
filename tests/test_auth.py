"""Offline auth tests (Part 32): Supabase ES256 JWTs verified against JWKS.

No network, no live Supabase. The `mint` fixture signs tokens with a per-session
P-256 key and registers its public JWK, so the real verifier runs exactly as it
does against a project's /auth/v1/.well-known/jwks.json.
"""
import time

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dealfinder import auth
from dealfinder.auth import User, require_role, require_user
from tests.conftest import bearer

app = FastAPI()


@app.get("/me")
def me(user: User = Depends(require_user)):
    return {"id": user.id, "email": user.email, "role": user.role}


@app.get("/pro")
def pro(user: User = Depends(require_role("pro"))):
    return {"ok": True, "id": user.id}


client = TestClient(app)


def test_valid_token_returns_user(mint):
    r = client.get("/me", headers=bearer(mint("user-123", email="a@b.com", app_metadata={"plan": "pro"})))
    assert r.status_code == 200 and r.json() == {"id": "user-123", "email": "a@b.com", "role": "pro"}


def test_expired_token(mint):
    r = client.get("/me", headers=bearer(mint(exp_delta=-10)))
    assert (r.status_code, r.json()["detail"]) == (401, "token expired")


def test_wrong_issuer(mint):
    assert client.get("/me", headers=bearer(mint(iss="https://evil.supabase.co/auth/v1"))).status_code == 401


def test_wrong_audience(mint):
    assert client.get("/me", headers=bearer(mint(aud="anon"))).status_code == 401


def test_unknown_kid(mint):
    assert client.get("/me", headers=bearer(mint(kid="other-kid"))).status_code == 401


def test_hs256_token_is_rejected(mint):
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "iss": "https://demo-ref.supabase.co/auth/v1",
                         "exp": int(time.time()) + 60}, "any-secret", algorithm="HS256")
    assert client.get("/me", headers=bearer(forged)).status_code == 401


def test_alg_none_is_rejected(mint):
    unsigned = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60}, None, algorithm="none")
    assert client.get("/me", headers=bearer(unsigned)).status_code == 401


def test_jwks_unreachable_fails_closed(mint, monkeypatch):
    token = mint()
    auth.set_jwks_for_testing(None)
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:9")
    r = client.get("/me", headers=bearer(token))
    assert (r.status_code, r.json()["detail"]) == (503, "auth unavailable")


def test_missing_supabase_url_fails_closed(mint, monkeypatch):
    token = mint()
    monkeypatch.delenv("SUPABASE_URL")
    assert client.get("/me", headers=bearer(token)).status_code == 503


def test_role_gate_forbids_other_plans(mint):
    assert client.get("/pro", headers=bearer(mint(app_metadata={"plan": "free"}))).status_code == 403
