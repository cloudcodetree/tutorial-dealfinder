"""scripts/cost_check.py: the default $0 preflight, and --live, which audits the deployed footprint."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("cost_check", Path("scripts/cost_check.py"))
cost_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cost_check)


def _service(min_scale="0", max_scale="2"):
    ann = {"autoscaling.knative.dev/maxScale": max_scale}
    if min_scale is not None:
        ann["autoscaling.knative.dev/minScale"] = min_scale
    return json.dumps({"spec": {"template": {"metadata": {"annotations": ann}}}})


@pytest.fixture
def fake_gcloud():
    """A subprocess.run stand-in answering the read-only gcloud calls live_report makes."""
    state = {"service": _service(), "jobs": {"dealfinder-prod-x": 0, "other-proj": 1}, "versions": 1,
             "size": "292294480", "budget": True}

    def run(argv, **kw):
        a = " ".join(argv)
        out = ""
        if "run services describe" in a:
            out = state["service"]
        elif "billing projects describe" in a:
            out = "billingAccounts/AAA-BBB-CCC\n"
        elif "billing projects list" in a:
            out = "\n".join(state["jobs"]) + "\n"
        elif "scheduler locations list" in a:
            out = "us-central1\n"
        elif "scheduler jobs list" in a:
            proj = argv[argv.index("--project") + 1]
            out = "".join(f"job{i}\n" for i in range(state["jobs"][proj]))
        elif "secrets versions list" in a:
            out = "".join(f"{i}\n" for i in range(state["versions"]))
        elif "artifacts repositories describe" in a:
            out = state["size"] + "\n"
        elif "projects describe" in a:
            out = "123456\n"
        elif "billing budgets list" in a:
            out = json.dumps([{"budgetFilter": {"projects": ["projects/123456"]}}] if state["budget"] else [])
        return subprocess.CompletedProcess(argv, 0, out, "")

    run.state = state
    return run


def _check(checks, name):
    return next(c for c in checks if c.name == name)


def test_live_report_passes_a_healthy_footprint(fake_gcloud):
    checks = cost_check.live_report(project="dealfinder-prod-x", run=fake_gcloud)
    assert checks and all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_live_report_flags_min_instances(fake_gcloud):
    fake_gcloud.state["service"] = _service(min_scale="1")
    checks = cost_check.live_report(project="dealfinder-prod-x", run=fake_gcloud)
    assert _check(checks, "cloud run min instances").ok is False


def test_live_report_flags_a_fourth_scheduler_job(fake_gcloud):
    fake_gcloud.state["jobs"] = {"dealfinder-prod-x": 0, "other-proj": 4}
    checks = cost_check.live_report(project="dealfinder-prod-x", run=fake_gcloud)
    assert _check(checks, "scheduler jobs on the billing account").ok is False


def test_live_report_flags_a_missing_budget_and_a_big_registry(fake_gcloud):
    fake_gcloud.state.update(budget=False, size="460000000")
    checks = cost_check.live_report(project="dealfinder-prod-x", run=fake_gcloud)
    assert _check(checks, "budget alert on the project").ok is False
    assert _check(checks, "artifact registry bytes").ok is False


def test_live_main_exit_code(monkeypatch):
    monkeypatch.setattr(cost_check, "live_report", lambda **k: [cost_check.Check("x", 0, 0, True)])
    assert cost_check.main(["--live", "--project", "p"]) == 0
    monkeypatch.setattr(cost_check, "live_report", lambda **k: [cost_check.Check("x", 1, 0, False)])
    assert cost_check.main(["--live", "--project", "p"]) == 1


def test_default_mode_unchanged(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k in ("DEALFINDER_ENABLE_PAID_SOURCES", "OPENROUTER_MODELS", "APIFY_TOKEN", "FIRECRAWL_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert cost_check.main([]) == 0


def test_a_project_without_the_scheduler_api_has_no_jobs(fake_gcloud):
    # gcloud's live wording: "API [cloudscheduler.googleapis.com] not enabled on project".
    inner = fake_gcloud

    def run(argv, **kw):
        if "scheduler" in argv and "locations" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "API [cloudscheduler.googleapis.com] not enabled on "
                                               "project [dealfinder-prod-x]. Would you like to enable and retry")
        return inner(argv, **kw)

    checks = cost_check.live_report(project="dealfinder-prod-x", run=run)
    jobs = _check(checks, "scheduler jobs on the billing account")
    assert jobs.value == 0 and jobs.ok


def test_every_gcloud_call_is_non_interactive(fake_gcloud):
    # A live run hung on gcloud's "enable this API? (y/N)" prompt waiting for stdin.
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw.get("stdin")))
        return fake_gcloud(argv, **kw)

    cost_check.live_report(project="dealfinder-prod-x", run=run)
    assert seen and all("--quiet" in argv and stdin is subprocess.DEVNULL for argv, stdin in seen)


def test_a_long_disabled_api_error_is_still_recognized(fake_gcloud):
    # The live message names the account and project first, so "has not been used"
    # sits past the 200 characters an error line keeps.
    long_err = ("ERROR: (gcloud.scheduler.locations.list) [chris@cloudcodetree.com] does not have permission to access "
                "projects instance [dealfinder-prod-x] (or it may not exist): " + "detail " * 30 +
                "Cloud Scheduler API has not been used in project dealfinder-prod-x before or it is disabled.")
    assert long_err.find("has not been used") > 200

    def run(argv, **kw):
        if "scheduler" in argv and "locations" in argv:
            return subprocess.CompletedProcess(argv, 1, "", long_err)
        return fake_gcloud(argv, **kw)

    jobs = _check(cost_check.live_report(project="dealfinder-prod-x", run=run), "scheduler jobs on the billing account")
    assert jobs.value == 0 and jobs.ok


def test_registry_size_falls_back_to_the_image_list_when_the_field_is_missing(fake_gcloud):
    # Live, `repositories describe` left sizeBytes out, and the check read that as 0.
    fake_gcloud.state["size"] = ""

    def run(argv, **kw):
        if "docker" in argv and "images" in argv:
            return subprocess.CompletedProcess(argv, 0, "1409\n297861942\n", "")
        return fake_gcloud(argv, **kw)

    size = _check(cost_check.live_report(project="dealfinder-prod-x", run=run), "artifact registry bytes")
    assert size.value == 297863351 and size.ok
