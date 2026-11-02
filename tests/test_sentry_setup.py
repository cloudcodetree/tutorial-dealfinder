"""scripts/sentry_setup.py: both projects, idempotently, alerting on, DSNs never printed."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import respx

spec = importlib.util.spec_from_file_location("sentry_setup", Path("scripts/sentry_setup.py"))
sentry_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sentry_setup)

API = "https://sentry.io/api/0"


def _mock(mock, create_status=201, rules=({"id": "1", "name": "Send a notification for high priority issues"},)):
    create = mock.post(f"{API}/teams/acme/core/projects/").mock(return_value=httpx.Response(create_status, json={}))
    for slug in ("dealfinder-api", "dealfinder-web"):
        mock.get(f"{API}/projects/acme/{slug}/keys/").mock(
            return_value=httpx.Response(200, json=[{"public": "pk", "dsn": {"public": f"https://pk@o1.ingest.us.sentry.io/{slug}"}}]))
        mock.get(f"{API}/projects/acme/{slug}/rules/").mock(return_value=httpx.Response(200, json=list(rules)))
    return create


def test_setup_creates_both_projects_with_default_alerting(tmp_path):
    with respx.mock() as mock:
        create = _mock(mock)
        sentry_setup.run(token="t", org="acme", team="core", out=tmp_path / "sentry.json")
    bodies = [json.loads(c.request.content) for c in create.calls]
    assert [(b["slug"], b["platform"], b["default_rules"]) for b in bodies] == [
        ("dealfinder-api", "python-fastapi", True), ("dealfinder-web", "javascript-react", True)]
    assert create.calls[0].request.headers["Authorization"] == "Bearer t"


def test_an_existing_project_is_reused(tmp_path):
    with respx.mock() as mock:
        _mock(mock, create_status=409)
        dsns = sentry_setup.run(token="t", org="acme", team="core", out=tmp_path / "sentry.json")
    assert set(dsns) == {"dealfinder-api", "dealfinder-web"}


def test_dsns_go_to_the_file_never_to_stdout(tmp_path, capsys):
    with respx.mock() as mock:
        _mock(mock)
        sentry_setup.run(token="t", org="acme", team="core", out=tmp_path / "sentry.json")
    saved = json.loads((tmp_path / "sentry.json").read_text())
    assert saved["dealfinder-api"].startswith("https://pk@") and "ingest" not in capsys.readouterr().out


def test_a_project_without_an_alert_rule_fails(tmp_path):
    with respx.mock(assert_all_called=False) as mock:   # it stops at the first project
        _mock(mock, rules=())
        with pytest.raises(RuntimeError, match="alert rule"):
            sentry_setup.run(token="t", org="acme", team="core", out=tmp_path / "sentry.json")
