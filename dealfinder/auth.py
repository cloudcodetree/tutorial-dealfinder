"""Auth & accounts (Part 32) — verifying Supabase-issued JWTs against JWKS.

Supabase Auth signs every session JWT with the project's asymmetric signing key
(ES256; RS256 also accepted) and publishes the public half at
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. The API verifies the signature,
expiry, issuer (`{SUPABASE_URL}/auth/v1`) and audience (`authenticated`) with that
public key. No shared secret exists anywhere. Keys are cached for 10 minutes,
so the hot path rarely calls Supabase, and a rotated-out key stops being
trusted at the next refresh.

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
import threading
import time

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_ALGORITHMS = ["ES256", "RS256"]
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=True)

_test_jwks: jwt.PyJWKSet | None = None

# JWKS cache rules (see _Jwks): keys are reused for _JWKS_TTL_S; an unknown kid
# refetches at most once per _JWKS_MIN_REFRESH_S; after a failed fetch, callers
# get 503 for _JWKS_RETRY_S without another network call, unless the last good
# key set still holds their kid.
_JWKS_TTL_S = 600.0
_JWKS_MIN_REFRESH_S = 60.0
_JWKS_RETRY_S = 30.0
_JWKS_TIMEOUT_S = 3.0


class _JwksUnavailable(Exception):
    """The key set could not be fetched or parsed."""


class _Jwks:
    """One project's signing keys, fetched with httpx and cached with explicit rules.

    PyJWKClient is not used because it keeps every key it has seen for the life of
    the process (a rotated-out key stays trusted), turns a non-JSON body or an
    empty set into a 500 or a 401 instead of an outage, and retries a failing
    endpoint on every request."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.keys: jwt.PyJWKSet | None = None
        self.fetched_at = float("-inf")
        self.failed_at = float("-inf")
        self.lock = threading.Lock()

    def _fetch(self) -> None:
        try:
            r = httpx.get(self.url, timeout=_JWKS_TIMEOUT_S)
            r.raise_for_status()
            keys = jwt.PyJWKSet.from_dict(r.json())
        except Exception as exc:  # network, HTTP status, non-JSON body, empty or invalid set
            self.failed_at = time.monotonic()
            raise _JwksUnavailable(str(exc)) from exc
        self.keys, self.fetched_at = keys, time.monotonic()

    def _lookup(self, kid: str | None) -> jwt.PyJWK | None:
        try:
            return self.keys[kid] if self.keys is not None else None
        except KeyError:
            return None

    def _needs_fetch(self, kid: str | None) -> bool:
        """Refetch when the set expired, or the kid is unknown and a refresh is allowed."""
        age = time.monotonic() - self.fetched_at
        return age >= _JWKS_TTL_S or (self._lookup(kid) is None and age >= _JWKS_MIN_REFRESH_S)

    def key_for(self, kid: str | None) -> jwt.PyJWK:
        key = self._lookup(kid)
        if not self._needs_fetch(kid):
            if key is None:
                raise jwt.InvalidKeyError(f"no signing key with kid {kid!r}")  # unknown kid, just refreshed
            return key
        if time.monotonic() - self.failed_at < _JWKS_RETRY_S:
            if key is not None:
                return key  # stale but last good, while the endpoint is failing
            raise _JwksUnavailable("recent fetch failed")
        if not self.lock.acquire(timeout=_JWKS_TIMEOUT_S):
            if key is not None:
                return key
            raise _JwksUnavailable("fetch in progress")
        try:
            if self._needs_fetch(kid):  # another thread may have fetched while we waited
                try:
                    self._fetch()
                except _JwksUnavailable:
                    if key is not None:
                        return key
                    raise
        finally:
            self.lock.release()
        key = self._lookup(kid)
        if key is None:
            raise jwt.InvalidKeyError(f"no signing key with kid {kid!r}")
        return key


_caches: dict[str, _Jwks] = {}
_caches_lock = threading.Lock()


def _reset_jwks_cache() -> None:
    """Forget every fetched key set (tests)."""
    with _caches_lock:
        _caches.clear()


def _cache_for(url: str) -> _Jwks:
    with _caches_lock:
        if url not in _caches:
            _caches[url] = _Jwks(url)
        return _caches[url]


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


def _key_from_set(token: str, keyset: jwt.PyJWKSet) -> jwt.PyJWK:
    kid = jwt.get_unverified_header(token).get("kid")
    try:
        return keyset[kid]
    except KeyError as exc:
        raise jwt.PyJWKClientError(f"no signing key with kid {kid!r}") from exc


def decode_claims(token: str, key: jwt.PyJWK, issuer: str) -> dict:
    """Verify one token against one JWK; 401 on any problem.

    Passing the PyJWK (not its raw key) lets PyJWT refuse a header alg that
    doesn't match the key's own alg, instead of crashing on it."""
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
    return decode_claims(token, key, issuer)


def verify_token(token: str) -> dict:
    """Return the verified claims of a Supabase session token.

    401 `token expired` / `invalid token` for a bad token, 503 `auth unavailable`
    when the project URL is unset or its JWKS can't be fetched."""
    issuer = f"{_supabase_url()}/auth/v1"
    try:
        if _test_jwks is not None:
            key = _key_from_set(token, _test_jwks)
        else:
            key = _cache_for(jwks_url()).key_for(jwt.get_unverified_header(token).get("kid"))
    except _JwksUnavailable as exc:
        raise _unavailable() from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    return decode_claims(token, key, issuer)


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
