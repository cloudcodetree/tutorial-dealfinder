"""Auth & accounts (Part 32) — verifying Supabase-issued JWTs.

This is the real, standard Supabase pattern: Supabase Auth signs every session
JWT with your project's JWT secret (HS256). Your API trusts a request by
verifying that signature with the same secret — no call back to Supabase needed
on the hot path. The secret lives in `SUPABASE_JWT_SECRET` (Project Settings →
API → JWT Secret in the Supabase dashboard).

`require_user` is a FastAPI dependency: drop it on any route and the route only
runs for a caller holding a valid, unexpired Supabase token. `require_role`
builds an RBAC gate on top (free vs. pro, etc.).

Runs live only with the learner's OWN Supabase project (set SUPABASE_JWT_SECRET
to that project's secret). The tests in `tests/test_auth.py` are fully offline:
they mint tokens with a throwaway secret and never touch the network.
"""
from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# Supabase signs session tokens with HS256 and the audience "authenticated".
_ALGO = "HS256"
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=True)


class User(BaseModel):
    """The authenticated principal, distilled from the verified JWT claims."""

    id: str  # Supabase `sub` — the stable user UUID
    email: str | None = None
    role: str = "free"  # app-level role; we read it from a custom claim (see below)


def _jwt_secret() -> str:
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        # Fail loud rather than silently accepting unsigned tokens.
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured")
    return secret


def _decode(token: str) -> dict:
    """Verify signature + expiry with the project secret; raise 401 on any problem."""
    try:
        return jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[_ALGO],
            audience=_AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        # Covers tampering, wrong secret, bad audience, malformed token, etc.
        raise HTTPException(status_code=401, detail="invalid token") from exc


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
    claims = _decode(creds.credentials)
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
