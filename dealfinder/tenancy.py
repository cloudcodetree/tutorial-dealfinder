"""Multi-tenancy — the request-scoped tenant context every SaaS is built on.

Two halves, and the second is the one people under-build:

1. **Resolve** which tenant a request belongs to (this module's `current_principal`).
2. **Enforce** that the request only ever touches that tenant's data. We push that
   down into Postgres Row-Level Security (see `pgstore.py`), so the *database*
   refuses to return another tenant's rows — an app-code bug can't leak across
   tenants. That's defense in depth, and it's the standard SaaS default (it's how
   Supabase itself works).

Resolution order (first hit wins), so the same code serves production and dev:
  1. the verified JWT's tenant claim (`app_metadata.tenant` / `org_id`) — production;
  2. an `X-Tenant-Id` header — local/dev/testing without minting real tokens;
  3. the default tenant ``"public"`` — anonymous/free public search.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header
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
    x_tenant_id: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency: resolve the request's `Principal` (tenant + identity).

    A valid token wins; otherwise fall back to the dev header, then the public
    tenant. Drop it on any route that reads or writes tenant-owned data:

        @app.get("/search")
        def search(q: str, who: Principal = Depends(current_principal)):
            ...
    """
    if creds is not None:
        claims = auth._decode(creds.credentials)  # verifies signature + expiry, or 401
        tenant = _tenant_from_claims(claims) or x_tenant_id or DEFAULT_TENANT
        return Principal(
            tenant_id=tenant,
            user_id=claims.get("sub"),
            role=auth._role_from_claims(claims),
        )
    return Principal(tenant_id=x_tenant_id or DEFAULT_TENANT, user_id=None, role="anonymous")
