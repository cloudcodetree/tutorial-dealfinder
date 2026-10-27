#!/usr/bin/env python3
"""Cost preflight — report which PAID surfaces your current environment has armed.

Read-only, stdlib-only (run it with no deps installed). It mirrors the gating in
`dealfinder/live_sources.py` and `dealfinder/llm.py` exactly:

  - a metered source is ARMED only when its key is set AND
    DEALFINDER_ENABLE_PAID_SOURCES=1;
  - the LLM only bills when OPENROUTER_MODELS points at a non-":free" model
    (the default tier is free-only).

Run it before starting the app ("am I about to spend money?") and after teardown
(confirm you're back to $0). Exit code 0 = nothing can bill; 1 = something is armed.
See COST.md.

`--live --project P` audits the deployed product instead (COST.md, Tier 3). It makes
read-only gcloud calls and checks each free-tier limit the design relies on: Cloud
Run scales to zero and stops at 2 instances, the billing account runs at most 3
Scheduler jobs, the secret has at most 6 active versions, the image repo stays under
450 MB, and a budget alert covers the project. Exit code 0 = every check passes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import NamedTuple

GREEN, YELLOW, RED, DIM, OFF = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def _load_dotenv(path: str = ".env") -> None:
    """Tiny, dependency-free .env reader so the check sees what the app will see.
    Does not override already-exported vars (same precedence as the app)."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Check(NamedTuple):
    name: str
    value: object
    limit: object
    ok: bool


REGION = "us-central1"
REGISTRY_MAX_BYTES = 450_000_000     # Artifact Registry gives 0.5 GB free
SCHEDULER_FREE_JOBS = 3              # per billing account, not per project
SECRET_FREE_VERSIONS = 6


def _gcloud(run, *args: str) -> str:
    proc = run(["gcloud", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gcloud {args[0]} {args[1]} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def _scheduler_jobs(run, project: str) -> int:
    """Jobs in every location of one project. A project without the API has none."""
    try:
        locations = _gcloud(run, "scheduler", "locations", "list", "--project", project,
                            "--format=value(locationId)").split()
    except RuntimeError as exc:
        if "SERVICE_DISABLED" in str(exc) or "has not been used" in str(exc):
            return 0
        raise
    return sum(len(_gcloud(run, "scheduler", "jobs", "list", "--project", project, "--location", loc,
                           "--format=value(name)").split()) for loc in locations)


def live_report(*, project: str, run=subprocess.run) -> list[Check]:
    """One Check per free-tier limit the deployed product relies on. Read-only."""
    checks: list[Check] = []
    svc = json.loads(_gcloud(run, "run", "services", "describe", "dealfinder-api", "--region", REGION,
                             "--project", project, "--format=json"))
    ann = svc["spec"]["template"]["metadata"].get("annotations", {})
    min_scale = int(ann.get("autoscaling.knative.dev/minScale", "0"))
    max_scale = int(ann.get("autoscaling.knative.dev/maxScale", "100"))
    checks.append(Check("cloud run min instances", min_scale, 0, min_scale == 0))
    checks.append(Check("cloud run max instances", max_scale, 2, max_scale <= 2))

    account = _gcloud(run, "billing", "projects", "describe", project,
                      "--format=value(billingAccountName)").strip().rsplit("/", 1)[-1]
    projects = _gcloud(run, "billing", "projects", "list", f"--billing-account={account}",
                       "--format=value(projectId)").split()
    jobs = sum(_scheduler_jobs(run, p) for p in projects)
    checks.append(Check("scheduler jobs on the billing account", jobs, SCHEDULER_FREE_JOBS,
                        jobs <= SCHEDULER_FREE_JOBS))

    versions = len(_gcloud(run, "secrets", "versions", "list", "dealfinder-env", "--project", project,
                           "--filter=state:ENABLED", "--format=value(name)").split())
    checks.append(Check("secret versions active", versions, SECRET_FREE_VERSIONS,
                        versions <= SECRET_FREE_VERSIONS))

    size = int(_gcloud(run, "artifacts", "repositories", "describe", "dealfinder", "--location", REGION,
                       "--project", project, "--format=value(sizeBytes)").strip() or 0)
    checks.append(Check("artifact registry bytes", size, REGISTRY_MAX_BYTES, size <= REGISTRY_MAX_BYTES))

    number = _gcloud(run, "projects", "describe", project, "--format=value(projectNumber)").strip()
    budgets = json.loads(_gcloud(run, "billing", "budgets", "list", f"--billing-account={account}",
                                 "--format=json") or "[]")
    covered = any(f"projects/{number}" in b.get("budgetFilter", {}).get("projects", []) for b in budgets)
    checks.append(Check("budget alert on the project", covered, True, covered))
    return checks


def _live(project: str) -> int:
    try:
        checks = live_report(project=project)
    except RuntimeError as exc:
        print(f"{RED}✗ {exc}{OFF}")
        return 1
    for c in checks:
        mark = f"{GREEN}✓" if c.ok else f"{RED}✗"
        print(f"{mark} {c.name}: {c.value} (limit {c.limit}){OFF}")
    return 0 if all(c.ok for c in checks) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DealFinder cost preflight. See COST.md.")
    ap.add_argument("--live", action="store_true", help="audit the deployed product (needs gcloud)")
    ap.add_argument("--project", help="the GCP project, with --live")
    args = ap.parse_args(argv)
    if args.live:
        if not args.project:
            ap.error("--live needs --project")
        return _live(args.project)

    _load_dotenv()
    paid_ok = os.getenv("DEALFINDER_ENABLE_PAID_SOURCES") == "1"

    # (label, env var that supplies the key, cost) — Apify + Amazon share APIFY_TOKEN.
    metered = [
        ("Apify (Google-Shopping actor)", "APIFY_TOKEN", "pay-per-event credits"),
        ("Amazon (Apify 'junglee' actor)", "APIFY_TOKEN", "14-day trial, then ~$40+/mo"),
        ("Firecrawl (broad-web)", "FIRECRAWL_API_KEY", "free credits, then paid"),
    ]
    armed = [(name, cost) for name, key, cost in metered if paid_ok and os.getenv(key)]

    models = os.getenv("OPENROUTER_MODELS", "")
    paid_models = [m.strip() for m in models.split(",")
                   if m.strip() and not m.strip().endswith(":free")]

    print(f"{DIM}DealFinder cost preflight — mirrors the gating in the code.{OFF}\n")

    if not armed and not paid_models:
        print(f"{GREEN}✓ No paid surfaces armed — you're at $0.{OFF}")
        # Informational: keys present but safely disarmed.
        dormant = [k for k in ("APIFY_TOKEN", "FIRECRAWL_API_KEY")
                   if os.getenv(k) and not paid_ok]
        if dormant:
            print(f"{DIM}  (keys present but DEALFINDER_ENABLE_PAID_SOURCES is off, "
                  f"so they cannot bill: {', '.join(dormant)}){OFF}")
        if os.getenv("OPENROUTER_API_KEY"):
            print(f"{DIM}  (OPENROUTER_API_KEY set, but the default model tier is "
                  f"free-only — no per-token charges){OFF}")
        return 0

    print(f"{RED}⚠ Paid surfaces are ARMED — running the app can incur charges:{OFF}")
    for name, cost in armed:
        print(f"  {YELLOW}• {name}{OFF} — {cost}")
    for m in paid_models:
        print(f"  {YELLOW}• LLM model {m}{OFF} — per-token (non-free)")
    print(f"\n{DIM}Disarm: unset DEALFINDER_ENABLE_PAID_SOURCES and OPENROUTER_MODELS "
          f"(and revoke keys / cancel rentals). See COST.md → Teardown.{OFF}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
