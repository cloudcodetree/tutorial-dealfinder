"""The shared Supabase project's admin connection, for production schema work. Prints no secret.

    python deploy/prod_db.py migrate --dry-run     # list pending dealfinder migrations, apply none
    python deploy/prod_db.py migrate               # apply them (owner go first)

The admin connection comes only from the site's env file (`--site-env`), the same
place `scripts/db-migrate.mjs` in the site repo reads it: SUPABASE_DIRECT_CON_STRING,
with its `[YOUR-PASSWORD]` placeholder filled from SUPABASE_DB_PASSWORD. A local
`.env` is never consulted, so a developer's DATABASE_URL or MIGRATION_DATABASE_URL
can never turn a production migration into a local one, or the reverse.

TLS is verify-full against Supabase's published CA, the copy the site commits at
`supabase/prod-ca-2021.crt`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from dealfinder import migrate

SITE = Path.home() / "Development" / "cloudcodetree.com"
SITE_ENV = SITE / ".env"
SITE_CA = SITE / "supabase" / "prod-ca-2021.crt"
PLACEHOLDER = "[YOUR-PASSWORD]"


def admin_url(site: dict[str, str], *, ca: Path) -> str:
    conn = site.get("SUPABASE_DIRECT_CON_STRING")
    if not conn:
        raise RuntimeError("no admin connection: SUPABASE_DIRECT_CON_STRING is missing from the site's env file")
    pw = site.get("SUPABASE_DB_PASSWORD")
    if pw and PLACEHOLDER in conn:
        conn = conn.replace(PLACEHOLDER, quote(pw, safe=""))
    parts = urlsplit(conn)
    if pw and PLACEHOLDER not in conn and parts.password is None and parts.username:
        host = parts.netloc.split("@", 1)[1]
        parts = parts._replace(netloc=f"{parts.username}:{quote(pw, safe='')}@{host}")
    query = dict(parse_qsl(parts.query))
    query.update(sslmode="verify-full", sslrootcert=str(ca))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _admin(site_env: Path) -> str:
    from dotenv import dotenv_values

    if not SITE_CA.exists():
        raise RuntimeError(f"Supabase CA not found at {SITE_CA}")
    site = dotenv_values(site_env) if site_env.exists() else {}
    return admin_url(site, ca=SITE_CA)


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
