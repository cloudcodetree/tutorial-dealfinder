"""Offline auth tests (Part 28).

No network, no live Supabase. We mint tokens with a throwaway secret via the
same HS256 scheme Supabase uses, then exercise the real verifier. Live use needs
the learner's own SUPABASE_JWT_SECRET; the logic under test is identical.
"""
import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dealfinder.auth import User, require_role, require_user

SECRET = "test-jwt-secret-not-real"


def _token(secret=SECRET, *, sub="user-123", email="a@b.com", role="free", exp_delta=3600, **extra):
    now = int(time.time())
    claims = {
        "sub": sub,
        "email": email,
        "aud": "authenticated",
        "iat": now,
        "exp": now + exp_delta,
        "app_metadata": {"plan": role},
        **extra,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)


# --- a tiny app that mounts the real dependencies --------------------------
app = FastAPI()


@app.get("/me")
def me(user: User = Depends(require_user)):
    return {"id": user.id, "email": user.email, "role": user.role}


@app.get("/pro")
def pro(user: User = Depends(require_role("pro"))):
    return {"ok": True, "id": user.id}


client = TestClient(app)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_valid_token_returns_user():
    r = client.get("/me", headers=_auth(_token(sub="u1", email="x@y.com", role="pro")))
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "email": "x@y.com", "role": "pro"}


def test_expired_token_is_401():
    r = client.get("/me", headers=_auth(_token(exp_delta=-10)))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]


def test_tampered_token_is_401():
    tok = _token()
    tampered = tok[:-3] + ("aaa" if tok[-3:] != "aaa" else "bbb")
    r = client.get("/me", headers=_auth(tampered))
    assert r.status_code == 401


def test_wrong_secret_is_401():
    r = client.get("/me", headers=_auth(_token(secret="some-other-secret")))
    assert r.status_code == 401


def test_missing_bearer_is_rejected():
    # HTTPBearer(auto_error=True) rejects a request with no credentials
    # (401 Not authenticated) before the route body ever runs.
    assert client.get("/me").status_code == 401


def test_require_role_allows_pro_blocks_free():
    assert client.get("/pro", headers=_auth(_token(role="pro"))).status_code == 200
    r = client.get("/pro", headers=_auth(_token(role="free")))
    assert r.status_code == 403
    assert "requires role 'pro'" in r.json()["detail"]
