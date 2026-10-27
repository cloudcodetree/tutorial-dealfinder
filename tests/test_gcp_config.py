"""Static checks on the GCP OpenTofu stack (deploy/gcp). They read the .tf text and
need no network, so a change that would cost money or leak a secret fails offline."""

import re
from pathlib import Path

import pytest

GCP = Path("deploy/gcp")


@pytest.fixture(scope="module")
def TF():
    files = sorted(GCP.glob("*.tf"))
    assert files, "deploy/gcp has no .tf files"
    return "\n".join(f.read_text() for f in files)


def test_scales_to_zero_and_is_capped(TF):
    assert re.search(r"min_instance_count\s*=\s*0\b", TF)
    assert re.search(r"max_instance_count\s*=\s*2\b", TF)


def test_everything_is_in_us_central1(TF):
    assert re.search(r'variable "region"\s*{[^}]*default\s*=\s*"us-central1"', TF)


def test_no_secret_values_in_state(TF):
    assert "google_secret_manager_secret_version" not in TF


def test_wif_is_pinned_to_this_repo_and_main(TF):
    cond = re.search(r"attribute_condition\s*=\s*\"([^\"]*)\"", TF).group(1)
    assert "assertion.repository ==" in cond and "assertion.ref == 'refs/heads/main'" in cond


def test_ci_owns_the_image(TF):
    assert len(re.findall(r"ignore_changes\s*=", TF)) >= 1


def test_budget_is_one_dollar(TF):
    assert re.search(r'units\s*=\s*"1"', TF)


def test_no_scheduled_jobs_at_launch(TF):
    # Launch without Best Buy (2026-10-27): nothing to schedule, so no Scheduler job
    # spends the billing account's 3 free ones.
    assert "google_cloud_scheduler_job" not in TF and "google_cloud_run_v2_job" not in TF
    assert "cloudscheduler" not in TF


def test_production_env_runs_best_buy_only_in_check_mode(TF):
    assert re.search(r'name\s*=\s*"DEALFINDER_ENV"\s*\n\s*value\s*=\s*"production"', TF)
    assert re.search(r'name\s*=\s*"DEALFINDER_SOURCES"\s*\n\s*value\s*=\s*"BestBuy"', TF)
    assert re.search(r'variable "verdict_mode"\s*{[^}]*default\s*=\s*"check"', TF)
