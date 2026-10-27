"""Create (or rotate) the production login role and store its pooler URL. Prints no secret.

    python deploy/create_login_role.py --project P [--rotate]

`dealfinder_svc` is the only role Cloud Run logs in as. It is LOGIN, NOSUPERUSER,
NOBYPASSRLS and NOINHERIT, and holds `dealfinder_app` and `dealfinder_job`. NOINHERIT
means it has no table rights of its own: every query runs inside `db.scoped` or
`db.job_scope`, which `SET LOCAL ROLE` to one of those two. The only direct grants
are USAGE on the schema and SELECT on `schema_migrations`, which `/readyz` reads
before any role is set.

Credentials are read here, from env files, and nowhere else:
- the admin connection: MIGRATION_DATABASE_URL, else SUPABASE_DIRECT_CON_STRING,
  from the companion's `.env` in the current directory
- the Supabase Management token and project ref: SUPABASE_ACCESS_TOKEN and
  SUPABASE_PROJECT_ID, from the site's env file (`--site-env`)
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from urllib.parse import quote

from psycopg import sql

ROLE = "dealfinder_svc"
SITE_ENV = Path.home() / "Development" / "cloudcodetree.com" / ".env"


def role_statements(password: str, *, rotate: bool = False) -> list[sql.Composed]:
    pw = sql.Literal(password)
    first = (sql.SQL("ALTER ROLE dealfinder_svc PASSWORD {}").format(pw) if rotate else
             sql.SQL("CREATE ROLE dealfinder_svc LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT PASSWORD {}").format(pw))
    return [first] + [sql.Composed([sql.SQL(s)]) for s in (
        "GRANT dealfinder_app TO dealfinder_svc",
        "GRANT dealfinder_job TO dealfinder_svc",
        "GRANT USAGE ON SCHEMA dealfinder TO dealfinder_svc",
        "GRANT SELECT ON dealfinder.schema_migrations TO dealfinder_svc",
    )]


def pooler_url(ref: str, host: str, password: str) -> str:
    """The transaction pooler (port 6543). Supavisor names the tenant in the user."""
    return f"postgresql://{ROLE}.{ref}:{quote(password, safe='')}@{host}:6543/postgres?sslmode=require"


def _pooler_host(ref: str, token: str) -> str:
    import httpx

    r = httpx.get(f"https://api.supabase.com/v1/projects/{ref}/config/database/pooler",
                  headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"pooler lookup failed: HTTP {r.status_code}")
    rows = r.json()
    rows = rows if isinstance(rows, list) else [rows]
    for row in rows:
        if row.get("pool_mode") == "transaction" or row.get("database_type") == "PRIMARY":
            return row["db_host"]
    raise RuntimeError("pooler lookup returned no primary pooler")


def _secrets_module():
    spec = importlib.util.spec_from_file_location("deploy_secrets", Path(__file__).with_name("secrets.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    from dotenv import dotenv_values
    import psycopg

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--rotate", action="store_true")
    ap.add_argument("--site-env", type=Path, default=SITE_ENV)
    args = ap.parse_args(argv)

    local = dotenv_values(Path(".env")) if Path(".env").exists() else {}
    admin = local.get("MIGRATION_DATABASE_URL") or local.get("SUPABASE_DIRECT_CON_STRING")
    site = dotenv_values(args.site_env) if args.site_env.exists() else {}
    ref, token = site.get("SUPABASE_PROJECT_ID"), site.get("SUPABASE_ACCESS_TOKEN")
    missing = [n for n, v in (("MIGRATION_DATABASE_URL or SUPABASE_DIRECT_CON_STRING", admin),
                              ("SUPABASE_PROJECT_ID", ref), ("SUPABASE_ACCESS_TOKEN", token)) if not v]
    if missing:
        print(f"✗ missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    deploy_secrets = _secrets_module()
    password = deploy_secrets.new_token()
    with psycopg.connect(admin, autocommit=False) as conn:
        for stmt in role_statements(password, rotate=args.rotate):
            conn.execute(stmt)
    host = _pooler_host(ref, token)
    n = deploy_secrets.merge({"DATABASE_URL": pooler_url(ref, host, password)}, project=args.project)
    print(f"✓ {ROLE} ready, DATABASE_URL stored in dealfinder-env v{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
