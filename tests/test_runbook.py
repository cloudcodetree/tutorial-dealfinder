"""RUNBOOK "Secrets": every credential production holds at launch has a rotation row,
and Cloud Run's URL-logging request log is excluded."""
from pathlib import Path

# What production holds at launch (Plan 5, "Launch without Best Buy"). The Best Buy,
# eBay, R2, Resend and job-check keys arrive with the follow-up and get rows then.
LAUNCH_SECRETS = ["DATABASE_URL", "EDGE_SHARED_SECRET", "UNSUBSCRIBE_SECRET", "CLOUDFLARE_ACCOUNT_ID",
                  "CLOUDFLARE_AI_TOKEN", "SENTRY_DSN", "HEALTHCHECK_UPTIME_URL", "CLOUDFLARE_EDGE_TOKEN",
                  "VITE_SENTRY_DSN"]
COLUMNS = "| Key | Store | Scope | Spend cap | Rotate | Verify |"


def _secrets_section() -> str:
    return Path("RUNBOOK.md").read_text().split("## Secrets", 1)[1].split("\n## ", 1)[0]


def test_every_secret_has_a_rotation_row():
    section = _secrets_section()
    assert COLUMNS in section
    assert [k for k in LAUNCH_SECRETS if f"| `{k}` |" not in section] == []


def test_spend_caps_are_written_down():
    section = _secrets_section()
    for phrase in ("10,000 neurons", "5,000 errors", "$1 budget", "no production key"):
        assert phrase in section, phrase


def test_cloud_run_request_logs_are_excluded():
    tf = "".join(p.read_text() for p in Path("deploy/gcp").glob("*.tf"))
    assert "google_logging_project_exclusion" in tf and "run.googleapis.com%2Frequests" in tf


def test_cost_rows_cover_the_new_free_services():
    cost = Path("COST.md").read_text().split("## Tier 3", 1)[1].split("\n## ", 1)[0]
    for service in ("Sentry", "Healthchecks.io", "Workers AI", "uptime cron"):
        assert service in cost, service
