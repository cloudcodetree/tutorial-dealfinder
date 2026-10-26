"""Auth & accounts (Part 32) — verifying Supabase-issued JWTs against JWKS.

Supabase Auth signs every session JWT with the project's asymmetric signing key
(ES256; RS256 also accepted) and publishes the public half at
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. The API verifies the signature,
expiry, issuer (`{SUPABASE_URL}/auth/v1`) and audience (`authenticated`) with that
public key. No shared secret exists anywhere, and the keys are cached for 10
minutes, so the hot path never calls Supabase.

This replaces Part 32's earlier HS256 shared-secret pattern (`SUPABASE_JWT_SECRET`).
Only ES256/RS256 are accepted, so an HS256 or `alg: none` token can never be
forged into a valid one.

Fail closed: no `SUPABASE_URL`, or a JWKS that can't be fetched, is a 503
`auth unavailable` — never a silent accept. A bad token is a 401.

`require_user` is a FastAPI dependency: drop it on any route and the route only
runs for a caller holding a valid, unexpired Supabase token. `require_role`
builds an RBAC gate on top (free vs. pro, etc.).

The tests in `tests/test_auth.py` are fully offline: the `mint` fixture signs
tokens with a throwaway P-256 key and registers its JWK via
`set_jwks_for_testing`.
"""
from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_ALGORITHMS = ["ES256", "RS256"]
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=True)

_test_jwks: jwt.PyJWKSet | None = None
_clients: dict[str, jwt.PyJWKClient] = {}


class User(BaseModel):
    """The authenticated principal, distilled from the verified JWT claims."""

    id: str  # Supabase `sub` — the stable user UUID
    email: str | None = None
    role: str = "free"  # app-level role; we read it from a custom claim (see below)


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="auth unavailable")


def _supabase_url() -> str:
    url = os.getenv("SUPABASE_URL")
    if not url:
        raise _unavailable()
    return url.rstrip("/")


def jwks_url() -> str:
    """The project's public signing keys."""
    return f"{_supabase_url()}/auth/v1/.well-known/jwks.json"


def set_jwks_for_testing(jwks: dict | None) -> None:
    """Verify against this JWK Set instead of fetching one. `None` restores fetching."""
    global _test_jwks
    _test_jwks = jwt.PyJWKSet.from_dict(jwks) if jwks is not None else None


def _client(url: str) -> jwt.PyJWKClient:
    if url not in _clients:
        _clients[url] = jwt.PyJWKClient(url, cache_keys=True, lifespan=600, timeout=5)
    return _clients[url]


def _key_from_set(token: str, keyset: jwt.PyJWKSet) -> jwt.PyJWK:
    kid = jwt.get_unverified_header(token).get("kid")
    try:
        return keyset[kid]
    except KeyError as exc:
        raise jwt.PyJWKClientError(f"no signing key with kid {kid!r}") from exc


def decode_claims(token: str, key, issuer: str) -> dict:
    """Verify one token against one public key; 401 on any problem."""
    try:
        return jwt.decode(token, key, algorithms=_ALGORITHMS, audience=_AUDIENCE, issuer=issuer)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.PyJWTError as exc:
        # Covers tampering, wrong key, wrong alg, bad issuer/audience, malformed token.
        raise HTTPException(status_code=401, detail="invalid token") from exc


def verify_with_jwks(token: str, jwks: dict, issuer: str) -> dict:
    """Verify a token against an explicit JWK Set. No global state, no network."""
    try:
        key = _key_from_set(token, jwt.PyJWKSet.from_dict(jwks))
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    return decode_claims(token, key.key, issuer)


def verify_token(token: str) -> dict:
    """Return the verified claims of a Supabase session token.

    401 `token expired` / `invalid token` for a bad token, 503 `auth unavailable`
    when the project URL is unset or its JWKS can't be fetched."""
    issuer = f"{_supabase_url()}/auth/v1"
    try:
        if _test_jwks is not None:
            key = _key_from_set(token, _test_jwks)
        else:
            key = _client(jwks_url()).get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as exc:
        raise _unavailable() from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    return decode_claims(token, key.key, issuer)


def _role_from_claims(claims: dict) -> str:
    """App role lives in a custom claim.

    Supabase puts the *Postgres* role ("authenticated") in the top-level `role`
    claim, which is not the app-level plan. The convention is to stamp the plan
    via a custom claim (an auth hook / `app_metadata.plan`), so we look there
    first and fall back to "free".
    """
    app_meta = claims.get("app_metadata") or {}
    return claims.get("user_role") or app_meta.get("plan") or app_meta.get("role") or "free"


def require_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> User:
    """FastAPI dependency: return the verified `User` or raise 401.

    Usage:
        @app.get("/me")
        def me(user: User = Depends(require_user)):
            return user
    """
    claims = verify_token(creds.credentials)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token missing subject")
    return User(id=sub, email=claims.get("email"), role=_role_from_claims(claims))


def require_role(role: str):
    """Build a dependency that requires `user.role == role` (RBAC gate).

    Example:
        pro_only = require_role("pro")

        @app.get("/pro/export")
        def export(user: User = Depends(pro_only)):
            ...
    """

    def _dep(user: User = Depends(require_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail=f"requires role '{role}'")
        return user

    return _dep
