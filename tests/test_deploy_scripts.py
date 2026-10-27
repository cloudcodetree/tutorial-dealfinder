"""deploy/secrets.py and deploy/create_login_role.py: values go to stdin, never argv or stdout."""

import importlib.util
import json
import subprocess
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(name, Path("deploy") / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


secrets_mod = _load("secrets")
login_mod = _load("create_login_role")


class Call:
    def __init__(self, argv, stdin):
        self.argv, self.stdin = argv, stdin


class FakeRun:
    """Stands in for subprocess.run with canned gcloud answers."""

    def __init__(self, versions=(), latest=None):
        self.versions = list(versions)
        self.latest = latest
        self.calls = []

    def __call__(self, argv, input=None, **kw):
        self.calls.append(Call(argv, input))
        out, rc, err = "", 0, ""
        if argv[:4] == ["gcloud", "secrets", "versions", "add"]:
            new = str(max([int(v) for v in self.versions] or [0]) + 1)
            self.versions.insert(0, new)
            out = new + "\n"
        elif argv[:4] == ["gcloud", "secrets", "versions", "list"]:
            out = "\n".join(self.versions) + "\n"
        elif argv[:4] == ["gcloud", "secrets", "versions", "access"]:
            if self.latest is None:
                rc, err = 1, "ERROR: NOT_FOUND: Secret Version [latest] not found."
            else:
                out = self.latest
        return subprocess.CompletedProcess(argv, rc, out, err)


def test_payload_keeps_only_contract_keys():
    p = json.loads(secrets_mod.build_payload({"BESTBUY_API_KEY": "k", "OPENROUTER_API_KEY": "nope"}))
    assert p == {"BESTBUY_API_KEY": "k"}


def test_push_sends_value_on_stdin_and_destroys_old_versions():
    fake = FakeRun(versions=["3", "2", "1"])
    assert secrets_mod.push('{"A":"v"}', project="p", run=fake) == 4
    add = fake.calls[0]
    assert "--data-file=-" in add.argv and add.stdin == '{"A":"v"}' and '{"A":"v"}' not in " ".join(add.argv)
    destroyed = {c.argv[4] for c in fake.calls if c.argv[:4] == ["gcloud", "secrets", "versions", "destroy"]}
    assert destroyed == {"1", "2", "3"}


def test_current_is_empty_before_the_first_version():
    assert secrets_mod.current(project="p", run=FakeRun()) == {}


def test_merge_keeps_what_is_stored():
    fake = FakeRun(versions=["1"], latest='{"DATABASE_URL": "prod", "SENTRY_DSN": "d"}')
    secrets_mod.merge({"SENTRY_DSN": "d2"}, project="p", run=fake)
    add = next(c for c in fake.calls if c.argv[:4] == ["gcloud", "secrets", "versions", "add"])
    assert json.loads(add.stdin) == {"DATABASE_URL": "prod", "SENTRY_DSN": "d2"}


def test_push_cli_prints_no_values(capsys, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BESTBUY_API_KEY=supersecretvalue\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(secrets_mod, "current", lambda **k: {})
    monkeypatch.setattr(secrets_mod, "push", lambda payload, **k: 7)
    secrets_mod.main(["push", "--project", "p"])
    out = capsys.readouterr().out
    assert "supersecretvalue" not in out and "BESTBUY_API_KEY" in out and "v7" in out


def test_push_cli_never_sends_the_local_database_url(monkeypatch, tmp_path):
    # The env file's DATABASE_URL is the developer's own database. Production's comes
    # only from create_login_role, and a push must keep it.
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://localhost/dev\nSENTRY_DSN=d\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(secrets_mod, "current", lambda **k: {"DATABASE_URL": "postgresql://prod"})
    sent = {}
    monkeypatch.setattr(secrets_mod, "push", lambda payload, **k: sent.update(json.loads(payload)) or 2)
    secrets_mod.main(["push", "--project", "p"])
    assert sent["DATABASE_URL"] == "postgresql://prod" and sent["SENTRY_DSN"] == "d"
    assert len(sent["EDGE_SHARED_SECRET"]) >= 40           # generated when absent


def test_check_cli_lists_names_only(capsys, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("SENTRY_DSN=topsecretdsn\n")
    monkeypatch.chdir(tmp_path)
    secrets_mod.main(["check"])
    out = capsys.readouterr().out
    assert "topsecretdsn" not in out and "SENTRY_DSN" in out and "BESTBUY_API_KEY" in out


def test_login_role_sql_never_uses_session_scope():
    sql = login_mod.role_statements("pw-literal")
    text = " ".join(s.as_string(None) if hasattr(s, "as_string") else str(s) for s in sql)
    assert "NOBYPASSRLS" in text and "NOINHERIT" in text and "SUPERUSER" not in text.replace("NOSUPERUSER", "")
    assert "GRANT dealfinder_app TO dealfinder_svc" in text and "GRANT dealfinder_job TO dealfinder_svc" in text
    assert "SELECT ON dealfinder.schema_migrations" in text


def test_rotate_alters_instead_of_creating():
    text = " ".join(s.as_string(None) for s in login_mod.role_statements("pw", rotate=True))
    assert text.startswith("ALTER ROLE dealfinder_svc") and "CREATE ROLE" not in text


def test_pooler_url_uses_the_transaction_pooler():
    url = login_mod.pooler_url("abcd", "aws-0-us-east-1.pooler.supabase.com", "p@ss/word")
    assert url == ("postgresql://dealfinder_svc.abcd:p%40ss%2Fword@aws-0-us-east-1.pooler.supabase.com"
                   ":6543/postgres?sslmode=require")


FAKE_GCLOUD = """#!/bin/sh
case "$*" in
  *"versions access"*) echo "ERROR: NOT_FOUND: Secret Version [latest] not found." >&2; exit 1 ;;
  *"versions add"*) cat > "$FAKE_GCLOUD_STDIN"; echo 1 ;;
  *"versions list"*) echo 1 ;;
esac
"""


def test_push_runs_as_a_script_with_a_fake_gcloud(tmp_path):
    # Run the way the runbook runs it. deploy/ is then first on sys.path, so a stdlib
    # name the script shadows (deploy/secrets.py vs `secrets`) breaks only here.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gcloud").write_text(FAKE_GCLOUD)
    (bin_dir / "gcloud").chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("SENTRY_DSN=hushhush\n")
    stdin_file = tmp_path / "stdin.json"
    import os
    import sys

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GCLOUD_STDIN": str(stdin_file)}
    proc = subprocess.run([sys.executable, str(Path("deploy/secrets.py").resolve()), "push", "--project", "p"],
                          cwd=work, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "✓ dealfinder-env v1" in proc.stdout and "hushhush" not in proc.stdout + proc.stderr
    stored = json.loads(stdin_file.read_text())
    assert stored["SENTRY_DSN"] == "hushhush" and len(stored["EDGE_SHARED_SECRET"]) >= 40


def test_login_role_script_imports_cleanly_as_a_script():
    import sys

    proc = subprocess.run([sys.executable, "deploy/create_login_role.py", "--help"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    for f in ("deploy/secrets.py", "deploy/create_login_role.py"):
        assert "import secrets\n" not in Path(f).read_text(), f"{f} shadows the stdlib secrets module"


def test_role_sql_never_carries_the_plain_password():
    # Postgres can log DDL (log_statement, pgaudit), so the statement holds only the
    # SCRAM-SHA-256 verifier, computed here.
    text = " ".join(s.as_string(None) for s in login_mod.role_statements("pw-literal-xyz"))
    assert "pw-literal-xyz" not in text and "SCRAM-SHA-256$4096:" in text


def test_scram_verifier_lets_the_password_log_in(db):
    import psycopg
    from psycopg import sql

    verifier = login_mod.scram_verifier("probe-pass-123")
    with psycopg.connect(db, autocommit=True) as admin:
        admin.execute("DROP ROLE IF EXISTS df_scram_probe")
        admin.execute(sql.SQL("CREATE ROLE df_scram_probe LOGIN PASSWORD {}").format(sql.Literal(verifier)))
        try:
            info = psycopg.conninfo.conninfo_to_dict(db)
            with psycopg.connect(**{**info, "user": "df_scram_probe", "password": "probe-pass-123"}) as c:
                assert c.execute("SELECT current_user").fetchone() == ("df_scram_probe",)
        finally:
            admin.execute("DROP ROLE df_scram_probe")
