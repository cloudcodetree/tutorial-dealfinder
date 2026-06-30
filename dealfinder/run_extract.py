"""Extract structured specs from messy listings.

Run:  python -m dealfinder.run_extract
(With an OpenAI-compatible client wired in, swap rule_extract for llm_extract.)
"""
from __future__ import annotations

from .extract import rule_extract

LISTINGS = [
    "TrailLite UL2 — ultralight 2-person tent, just 1.1kg, 3-season",
    "SummitPro 4-season expedition tent, sleeps 4, 3.2 kg",
    "BasecampCo family tent (sleeps 3), 2-season, 2400 g",
    "ValueOutdoors solo backpacker — 1 person, 3 season, 1.6kg",
]


def main() -> None:
    for text in LISTINGS:
        specs = rule_extract(text)
        print(f"• {text}")
        print(f"  → {specs.model_dump_json()}")


if __name__ == "__main__":
    main()
