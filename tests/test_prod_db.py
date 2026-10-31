"""deploy/prod_db.py: the shared project's admin connection, from the site's env file, TLS verified."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("prod_db", Path("deploy/prod_db.py"))
prod_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prod_db)

CA = Path("/site/supabase/prod-ca-2021.crt")


def test_admin_url_splices_the_password_and_verifies_tls():
    site = {"SUPABASE_DIRECT_CON_STRING": "postgresql://postgres:[YOUR-PASSWORD]@db.abcd.supabase.co:5432/postgres",
            "SUPABASE_DB_PASSWORD": "p@ss/w"}
    url = prod_db.admin_url(site, ca=CA)
    assert url.startswith("postgresql://postgres:p%40ss%2Fw@db.abcd.supabase.co:5432/postgres?")
    assert "sslmode=verify-full" in url and "sslrootcert=%2Fsite%2Fsupabase%2Fprod-ca-2021.crt" in url


def test_admin_url_sets_the_password_when_there_is_no_placeholder():
    site = {"SUPABASE_DIRECT_CON_STRING": "postgresql://postgres@db.abcd.supabase.co:5432/postgres?sslmode=require",
            "SUPABASE_DB_PASSWORD": "pw"}
    url = prod_db.admin_url(site, ca=CA)
    assert url.startswith("postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres?")
    assert "sslmode=require" not in url and "sslmode=verify-full" in url


def test_admin_url_needs_the_site_connection():
    with pytest.raises(RuntimeError, match="SUPABASE_DIRECT_CON_STRING") as e:
        prod_db.admin_url({"SUPABASE_DB_PASSWORD": "hunter2"}, ca=CA)
    assert "hunter2" not in str(e.value)


def test_migrate_dry_run_lists_pending_and_applies_nothing(monkeypatch, capsys):
    applied = []
    monkeypatch.setattr(prod_db, "_admin", lambda site_env: "postgresql://admin")
    monkeypatch.setattr(prod_db.migrate, "pending", lambda url: ["0003_job_role.sql", "0004_offer_provenance.sql"])
    monkeypatch.setattr(prod_db.migrate, "apply", lambda url: applied.append(url) or [])
    assert prod_db.main(["migrate", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "0003_job_role.sql" in out and "0004_offer_provenance.sql" in out and applied == []
    assert "admin" not in out
