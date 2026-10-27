"""Offline auth tests (Part 32): Supabase ES256 JWTs verified against JWKS.

No network, no live Supabase. The `mint` fixture signs tokens with a per-session
P-256 key and registers its public JWK, so the real verifier runs exactly as it
does against a project's /auth/v1/.well-known/jwks.json.
"""
import http.server
import json
import threading
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
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
                         "exp": int(time.time()) + 60}, "any-secret", algorithm="HS256",
                        headers={"kid": "test-kid"})
    assert client.get("/me", headers=bearer(forged)).status_code == 401


def test_alg_none_is_rejected(mint):
    unsigned = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60}, None, algorithm="none",
                          headers={"kid": "test-kid"})
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


def test_rs256_header_with_the_real_kid_is_401(mint):
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "iss": "https://demo-ref.supabase.co/auth/v1",
                         "exp": int(time.time()) + 60}, rsa_key, algorithm="RS256", headers={"kid": "test-kid"})
    assert client.get("/me", headers=bearer(forged)).status_code == 401


# ── The real fetch path, against a local JWKS server ─────────────────────────
@pytest.fixture
def jwks_server(_es256_key, monkeypatch):
    """Serve a JWK Set over HTTP; tests change state.status / state.body mid-test."""
    def keyset(key, kid):
        jwk = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
        return json.dumps({"keys": [{**jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}).encode()

    state = SimpleNamespace(status=200, hits=0, keyset=keyset)
    state.body = keyset(_es256_key, "test-kid")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state.hits += 1
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(state.body)

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state.base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setenv("SUPABASE_URL", state.base)
    auth.set_jwks_for_testing(None)
    auth._reset_jwks_cache()
    yield state
    srv.shutdown()
    auth._reset_jwks_cache()


def _signed(mint, server, **kw):
    return mint(iss=f"{server.base}/auth/v1", **kw)


def test_fetched_jwks_verifies_a_token(mint, jwks_server):
    assert client.get("/me", headers=bearer(_signed(mint, jwks_server))).status_code == 200


def test_rotated_out_key_is_rejected_after_refresh(mint, jwks_server, monkeypatch):
    monkeypatch.setattr(auth, "_JWKS_TTL_S", 0.05)
    token = _signed(mint, jwks_server)
    assert client.get("/me", headers=bearer(token)).status_code == 200
    jwks_server.body = jwks_server.keyset(ec.generate_private_key(ec.SECP256R1()), "new-kid")
    time.sleep(0.1)
    assert client.get("/me", headers=bearer(token)).status_code == 401


@pytest.mark.parametrize("status, body", [(200, b"<html>not json</html>"), (200, b'{"keys": []}'),
                                          (500, b'{"error": "boom"}')])
def test_broken_jwks_is_503(mint, jwks_server, status, body):
    token = _signed(mint, jwks_server)
    jwks_server.status, jwks_server.body = status, body
    r = client.get("/me", headers=bearer(token))
    assert (r.status_code, r.json()["detail"]) == (503, "auth unavailable")


def test_jwks_outage_fails_fast_after_one_failure(mint, jwks_server):
    token = _signed(mint, jwks_server)
    jwks_server.status = 500
    assert client.get("/me", headers=bearer(token)).status_code == 503
    hits, t0 = jwks_server.hits, time.monotonic()
    assert client.get("/me", headers=bearer(token)).status_code == 503
    assert jwks_server.hits == hits and time.monotonic() - t0 < 0.5


def test_last_good_keys_survive_a_failed_refresh(mint, jwks_server, monkeypatch):
    monkeypatch.setattr(auth, "_JWKS_TTL_S", 0.05)
    token = _signed(mint, jwks_server)
    assert client.get("/me", headers=bearer(token)).status_code == 200
    jwks_server.status = 500
    time.sleep(0.1)
    assert client.get("/me", headers=bearer(token)).status_code == 200


def test_unknown_kid_refetches_at_most_once_per_window(mint, jwks_server):
    assert client.get("/me", headers=bearer(_signed(mint, jwks_server))).status_code == 200
    stranger = _signed(mint, jwks_server, kid="other-kid")
    hits = jwks_server.hits
    assert client.get("/me", headers=bearer(stranger)).status_code == 401
    assert client.get("/me", headers=bearer(stranger)).status_code == 401
    assert jwks_server.hits - hits <= 1
