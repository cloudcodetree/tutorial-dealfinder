"""The shared Supabase project's admin connection, for production schema work. Prints no secret.

    python deploy/prod_db.py migrate --dry-run     # list pending dealfinder migrations, apply none
    python deploy/prod_db.py migrate               # apply them (owner go first)

Credentials come only from the site's env file (`--site-env`): SUPABASE_PROJECT_ID,
SUPABASE_DB_PASSWORD and the Supabase personal token, the `sbp_` value under
SUPABASE_ACCESS_TOKEN or GOOGLE_ACCESS_TOKEN, as the site's scripts read it. A local `.env`
is never consulted, so a developer's DATABASE_URL or MIGRATION_DATABASE_URL can
never turn a production migration into a local one, or the reverse.

The connection goes through Supavisor's session pooler (port 5432, user
`postgres.<ref>`). Supabase's direct host `db.<ref>.supabase.co` is IPv6-only, and
neither a typical laptop nor Cloud Run's default egress has an IPv6 route. The
session pooler keeps one server connection per client, so DDL and migrations
behave as on a direct connection. TLS is verify-full against Supabase's published
CA, the copy the site commits at `supabase/prod-ca-2021.crt`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

from dealfinder import migrate

SITE = Path.home() / "Development" / "cloudcodetree.com"
SITE_ENV = SITE / ".env"
SITE_CA = SITE / "supabase" / "prod-ca-2021.crt"
SESSION_PORT = 5432


def management_token(site: dict[str, str]) -> str | None:
    """The Supabase personal token. The site keeps it under GOOGLE_ACCESS_TOKEN, so take
    whichever name holds an sbp_ value, the same rule as its supabase-allowlist.mjs."""
    for name in ("SUPABASE_ACCESS_TOKEN", "GOOGLE_ACCESS_TOKEN"):
        value = site.get(name) or ""
        if value.startswith("sbp_"):
            return value
    return None


def pooler_host(ref: str, token: str) -> str:
    """The project's Supavisor host, from the Management API. Errors name only the status."""
    import httpx

    r = httpx.get(f"https://api.supabase.com/v1/projects/{ref}/config/database/pooler",
                  headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"pooler lookup failed: HTTP {r.status_code}")
    rows = r.json()
    rows = rows if isinstance(rows, list) else [rows]
    for row in rows:
        if row.get("database_type") == "PRIMARY" or row.get("pool_mode") == "transaction":
            return row["db_host"]
    raise RuntimeError("pooler lookup returned no primary pooler")


def admin_url(site: dict[str, str], *, ca: Path, pooler_host: str) -> str:
    ref, pw = site.get("SUPABASE_PROJECT_ID"), site.get("SUPABASE_DB_PASSWORD")
    if not ref:
        raise RuntimeError("SUPABASE_PROJECT_ID is missing from the site's env file")
    if not pw:
        raise RuntimeError("SUPABASE_DB_PASSWORD is missing from the site's env file")
    query = urlencode({"sslmode": "verify-full", "sslrootcert": str(ca)})
    return f"postgresql://postgres.{ref}:{quote(pw, safe='')}@{pooler_host}:{SESSION_PORT}/postgres?{query}"


def _admin(site_env: Path) -> str:
    from dotenv import dotenv_values

    if not SITE_CA.exists():
        raise RuntimeError(f"Supabase CA not found at {SITE_CA}")
    site = dotenv_values(site_env) if site_env.exists() else {}
    ref, token = site.get("SUPABASE_PROJECT_ID"), management_token(site)
    if not ref or not token:
        raise RuntimeError("the site's env file needs SUPABASE_PROJECT_ID and an sbp_ personal token "
                           "(SUPABASE_ACCESS_TOKEN or GOOGLE_ACCESS_TOKEN)")
    return admin_url(site, ca=SITE_CA, pooler_host=pooler_host(ref, token))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--site-env", type=Path, default=SITE_ENV)
    args = ap.parse_args(argv)
    try:
        url = _admin(args.site_env)
        todo = migrate.pending(url)
        if args.dry_run:
            print(f"pending: {', '.join(todo) if todo else 'none'}")
            return 0
        done = migrate.apply(url)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ applied: {', '.join(done) if done else 'nothing, already current'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
