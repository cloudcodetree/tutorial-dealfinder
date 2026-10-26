"""Multi-tenancy — the request-scoped tenant context every SaaS is built on.

Two halves, and the second is the one people under-build:

1. **Resolve** which tenant a request belongs to (this module's `current_principal`).
2. **Enforce** that the request only ever touches that tenant's data. We push that
   down into Postgres Row-Level Security (see `pgstore.py`), so the *database*
   refuses to return another tenant's rows — an app-code bug can't leak across
   tenants. That's defense in depth, and it's the standard SaaS default (it's how
   Supabase itself works).

Resolution order (first hit wins):
  1. the verified JWT: its tenant claim (`app_metadata.tenant` / `org_id`) and `sub`;
  2. the default tenant ``"public"``, anonymous — public search.

No request header can set a user or a tenant. Identity comes only from a token
the JWKS verified (see `auth.py`).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth

DEFAULT_TENANT = "public"

# Optional bearer: unlike auth._bearer (auto_error=True), public search must work
# without a token, so a missing Authorization header is allowed here.
_optional_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """Who is making this request, and — the part that matters for isolation —
    which tenant's data they are scoped to."""

    tenant_id: str
    user_id: str | None = None
    role: str = "anonymous"


def _tenant_from_claims(claims: dict) -> str | None:
    """Where the tenant lives in a JWT. Supabase stamps org/tenant into a custom
    claim (an auth hook or `app_metadata`), so we look there."""
    app_meta = claims.get("app_metadata") or {}
    return (
        claims.get("tenant")
        or app_meta.get("tenant")
        or app_meta.get("tenant_id")
        or claims.get("org_id")
    )


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> Principal:
    """FastAPI dependency: resolve the request's `Principal` (tenant + identity).

    No token: the public tenant, anonymous. A valid token: its tenant claim (or
    public), its `sub` as the user, and its plan as the role. A bad token is 401
    and an auth outage is 503, both from `auth.verify_token`. Drop it on any route
    that reads or writes owned data:

        @app.get("/search")
        def search(q: str, who: Principal = Depends(current_principal)):
            ...
    """
    if creds is None:
        return Principal(tenant_id=DEFAULT_TENANT)
    claims = auth.verify_token(creds.credentials)
    return Principal(
        tenant_id=_tenant_from_claims(claims) or DEFAULT_TENANT,
        user_id=claims.get("sub"),
        role=auth._role_from_claims(claims),
    )


def require_account(who: Principal = Depends(current_principal)) -> Principal:
    """Gate consumer account features (watchlist, saved searches, alerts) behind a
    signed-in user. Anonymous public search never uses this — only personal data does."""
    if not who.user_id:
        raise HTTPException(status_code=401, detail="sign in to use account features")
    return who
