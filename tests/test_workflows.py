"""GitHub workflow rules: no expression inside run:, WIF instead of a JSON key, no cron."""

from pathlib import Path

import yaml


def _runs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "run":
                yield v
            else:
                yield from _runs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _runs(v)


def test_no_expressions_inside_run_blocks():
    for wf in Path(".github/workflows").glob("*.yml"):
        for script in _runs(yaml.safe_load(wf.read_text())):
            assert "${{" not in script, f"{wf.name}: move the expression into env:"


def test_deploy_uses_wif_not_a_json_key():
    text = Path(".github/workflows/ci.yml").read_text()
    assert "workload_identity_provider" in text and "credentials_json" not in text
    assert "id-token: write" in text


def test_no_schedule_trigger_anywhere():
    for wf in Path(".github/workflows").glob("*.yml"):
        assert "schedule" not in (yaml.safe_load(wf.read_text()).get(True) or {})   # PyYAML reads `on:` as True


def test_deploy_runs_only_on_a_push_to_main_after_both_test_jobs():
    deploy = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())["jobs"]["deploy"]
    assert set(deploy["needs"]) == {"test", "edge"}
    assert deploy["if"] == "github.ref == 'refs/heads/main' && github.event_name == 'push'"
    assert deploy["permissions"] == {"contents": "read", "id-token": "write"}
