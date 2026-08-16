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
"""
from __future__ import annotations

import os
import sys

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


def main() -> int:
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
