"""deploy/prod_db.py: the shared project's admin connection, from the site's env file, TLS verified.

Supabase's direct host is IPv6-only, which neither this laptop nor Cloud Run's
default egress can reach, so admin work goes through the session pooler (IPv4)."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("prod_db", Path("deploy/prod_db.py"))
prod_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prod_db)

CA = Path("/site/supabase/prod-ca-2021.crt")
POOLER = "aws-0-us-east-1.pooler.supabase.com"


def test_admin_url_uses_the_session_pooler_and_verifies_tls():
    site = {"SUPABASE_PROJECT_ID": "abcd", "SUPABASE_DB_PASSWORD": "p@ss/w"}
    url = prod_db.admin_url(site, ca=CA, pooler_host=POOLER)
    assert url.startswith(f"postgresql://postgres.abcd:p%40ss%2Fw@{POOLER}:5432/postgres?")
    assert "sslmode=verify-full" in url and "sslrootcert=%2Fsite%2Fsupabase%2Fprod-ca-2021.crt" in url


def test_admin_url_needs_the_password_and_never_echoes_it():
    with pytest.raises(RuntimeError, match="SUPABASE_DB_PASSWORD"):
        prod_db.admin_url({"SUPABASE_PROJECT_ID": "abcd"}, ca=CA, pooler_host=POOLER)
    with pytest.raises(RuntimeError, match="SUPABASE_PROJECT_ID") as e:
        prod_db.admin_url({"SUPABASE_DB_PASSWORD": "hunter2"}, ca=CA, pooler_host=POOLER)
    assert "hunter2" not in str(e.value)


def test_pooler_host_reads_the_management_api(monkeypatch):
    import httpx

    seen = {}

    def get(url, headers, timeout):
        seen.update(url=url, auth=headers["Authorization"])
        return httpx.Response(200, json=[{"database_type": "PRIMARY", "pool_mode": "transaction",
                                          "db_host": POOLER}])

    monkeypatch.setattr(httpx, "get", get)
    assert prod_db.pooler_host("abcd", "tok") == POOLER
    assert seen == {"url": "https://api.supabase.com/v1/projects/abcd/config/database/pooler", "auth": "Bearer tok"}


def test_pooler_host_failure_names_only_the_status(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(401, text="token tok is bad"))
    with pytest.raises(RuntimeError, match="HTTP 401") as e:
        prod_db.pooler_host("abcd", "tok")
    assert "tok is bad" not in str(e.value)


def test_migrate_dry_run_lists_pending_and_applies_nothing(monkeypatch, capsys):
    applied = []
    monkeypatch.setattr(prod_db, "_admin", lambda site_env: "postgresql://admin")
    monkeypatch.setattr(prod_db.migrate, "pending", lambda url: ["0003_job_role.sql", "0004_offer_provenance.sql"])
    monkeypatch.setattr(prod_db.migrate, "apply", lambda url: applied.append(url) or [])
    assert prod_db.main(["migrate", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "0003_job_role.sql" in out and "0004_offer_provenance.sql" in out and applied == []
    assert "admin" not in out


def test_management_token_is_the_sbp_value_under_either_name():
    # The site stores its Supabase personal token under GOOGLE_ACCESS_TOKEN, and its
    # scripts take whichever of the two names holds an sbp_ value.
    assert prod_db.management_token({"GOOGLE_ACCESS_TOKEN": "sbp_x"}) == "sbp_x"
    assert prod_db.management_token({"SUPABASE_ACCESS_TOKEN": "sbp_y", "GOOGLE_ACCESS_TOKEN": "ya29.z"}) == "sbp_y"
    assert prod_db.management_token({"GOOGLE_ACCESS_TOKEN": "ya29.z"}) is None
