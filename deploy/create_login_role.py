"""Create (or rotate) the production login role and store its pooler URL. Prints no secret.

    python deploy/create_login_role.py --project P [--rotate]

`dealfinder_svc` is the only role Cloud Run logs in as. It is LOGIN, NOSUPERUSER,
NOBYPASSRLS and NOINHERIT, and holds `dealfinder_app` and `dealfinder_job`. NOINHERIT
means it has no table rights of its own: every query runs inside `db.scoped` or
`db.job_scope`, which `SET LOCAL ROLE` to one of those two. The only direct grants
are USAGE on the schema and SELECT on `schema_migrations`, which `/readyz` reads
before any role is set.

Credentials are read here, from the site's env file (`--site-env`), and nowhere else:
- the admin connection, through `deploy/prod_db.py` (SUPABASE_DIRECT_CON_STRING plus
  SUPABASE_DB_PASSWORD, TLS verify-full against Supabase's CA)
- the Supabase Management token and project ref: SUPABASE_ACCESS_TOKEN and
  SUPABASE_PROJECT_ID
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import quote

from psycopg import sql

ROLE = "dealfinder_svc"
SITE_ENV = Path.home() / "Development" / "cloudcodetree.com" / ".env"


def scram_verifier(password: str, *, salt: bytes | None = None, iterations: int = 4096) -> str:
    """The SCRAM-SHA-256 verifier Postgres stores for `password` (RFC 5802, RFC 7677).

    Postgres accepts a verifier in place of a password and stores it as is, so the
    plaintext never reaches the server, where log_statement or pgaudit could log the
    DDL. The tokens here are ASCII, so SASLprep leaves them unchanged."""
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def role_statements(password: str, *, rotate: bool = False) -> list[sql.Composed]:
    pw = sql.Literal(scram_verifier(password))
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


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"deploy_{name}", Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prod_db():
    return _load("prod_db")


def _secrets_module():
    return _load("secrets")


def provision(admin: str, *, ref: str, token: str, project: str, rotate: bool,
              connect, pooler=_pooler_host, secrets_mod=None) -> int:
    """Set the role's password and store the matching DATABASE_URL, or change neither.

    Every lookup that can fail (the pooler host, reading the stored secret) runs
    before any DDL. The role change then runs in one open transaction, the secret
    is written, and only then does the transaction commit. A failed secret write
    rolls the password back, so Postgres and dealfinder-env never disagree."""
    secrets_mod = secrets_mod or _secrets_module()
    host = pooler(ref, token)
    secrets_mod.current(project=project)
    password = secrets_mod.new_token()
    import psycopg

    with connect(admin, autocommit=False) as conn:
        try:
            for stmt in role_statements(password, rotate=rotate):
                conn.execute(stmt)
        except psycopg.errors.DuplicateObject:
            raise RuntimeError(f"{ROLE} already exists: re-run with --rotate to set a new password") from None
        return secrets_mod.merge({"DATABASE_URL": pooler_url(ref, host, password)}, project=project)


def main(argv: list[str] | None = None) -> int:
    from dotenv import dotenv_values
    import psycopg

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--rotate", action="store_true")
    ap.add_argument("--site-env", type=Path, default=SITE_ENV)
    args = ap.parse_args(argv)

    site = dotenv_values(args.site_env) if args.site_env.exists() else {}
    ref, token = site.get("SUPABASE_PROJECT_ID"), site.get("SUPABASE_ACCESS_TOKEN")
    missing = [n for n, v in (("SUPABASE_PROJECT_ID", ref), ("SUPABASE_ACCESS_TOKEN", token)) if not v]
    if missing:
        print(f"✗ missing from the site's env file: {', '.join(missing)}", file=sys.stderr)
        return 1
    try:
        admin = _prod_db()._admin(args.site_env)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    try:
        n = provision(admin, ref=ref, token=token, project=args.project, rotate=args.rotate,
                      connect=psycopg.connect)
    except RuntimeError as exc:
        print(f"✗ {exc}. Postgres is unchanged.", file=sys.stderr)
        return 1
    print(f"✓ {ROLE} ready, DATABASE_URL stored in dealfinder-env v{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
