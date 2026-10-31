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


def _deploy_steps():
    return yaml.safe_load(Path(".github/workflows/ci.yml").read_text())["jobs"]["deploy"]["steps"]


def _index(steps, needle):
    for i, s in enumerate(steps):
        if needle in (s.get("run", "") + s.get("uses", "") + s.get("name", "")):
            return i
    raise AssertionError(f"no step with {needle!r}")


def test_deploy_refuses_the_placeholder_backend_before_anything_ships():
    steps = _deploy_steps()
    guard = _index(steps, "backend-not-deployed.invalid")
    assert guard < _index(steps, "docker/build-push-action") and guard < _index(steps, "wrangler deploy")


def test_cloud_credentials_never_reach_npm_install_scripts():
    deploy = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())["jobs"]["deploy"]
    assert "CLOUDFLARE_API_TOKEN" not in deploy.get("env", {})
    steps = deploy["steps"]
    wrangler = steps[_index(steps, "wrangler deploy")]
    assert "CLOUDFLARE_API_TOKEN" in wrangler.get("env", {})
    auth = _index(steps, "google-github-actions/auth")
    installs = [i for i, s in enumerate(steps) if "npm ci" in s.get("run", "")]
    assert installs and all(i < auth for i in installs)
    assert "gha-creds-*.json" in Path(".dockerignore").read_text().split()


def test_smoke_check_avoids_the_path_cloud_run_reserves():
    smoke = _deploy_steps()[_index(_deploy_steps(), "smoke check")]["run"]
    assert "/api/health " in smoke + " " and "/api/healthz" not in smoke and "/api/readyz" in smoke


def test_smoke_check_targets_the_beta_host_before_launch():
    smoke = _deploy_steps()[_index(_deploy_steps(), "smoke check")]["run"]
    assert "https://deals.beta.cloudcodetree.com/api/health" in smoke
    assert "https://deals.cloudcodetree.com" not in smoke


def test_ci_reuses_image_layers_between_deploys():
    steps = _deploy_steps()
    build = steps[_index(steps, "docker/build-push-action")]
    assert build["with"]["cache-from"] == "type=gha" and build["with"]["cache-to"] == "type=gha,mode=max"
    assert build["with"]["push"] is True


def test_ci_pushes_a_single_manifest():
    # With provenance on, each push stored an index, a ~300 MB manifest and an
    # attestation. Deleting the tag left the manifest behind, and the keep-2 cleanup
    # policy counts each digest as a version.
    steps = _deploy_steps()
    assert steps[_index(steps, "docker/build-push-action")]["with"]["provenance"] is False
