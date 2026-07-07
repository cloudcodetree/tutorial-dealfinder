"""Guardrails: the boring-but-hireable layer that keeps an AI system safe.

Defense in depth — never trust input, never trust model output, and log
everything:
  - detect_prompt_injection: flag user text trying to hijack instructions.
  - redact_pii: strip emails / phones / cards before logging or prompting.
  - validate_listing_specs: value checks beyond type (a schema says str; this
    says a *known* category and a valid condition).
  - AuditLog: a tamper-evident-ish trail of who did what.
"""
from __future__ import annotations

import re

from .extract import KNOWN_CATEGORIES, ListingSpecs

_VALID_CONDITIONS = {"new", "refurb", "used"}

_INJECTION = [
    r"ignore (all |the )?previous",
    r"disregard .*instructions",
    r"system prompt",
    r"reveal .*(secret|key|password|prompt)",
    r"you are now",
]


def detect_prompt_injection(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in _INJECTION)


_EMAIL = r"[\w.+-]+@[\w-]+\.[\w.-]+"
_CARD = r"\b(?:\d[ -]?){13,16}\b"
_PHONE = r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"


def redact_pii(text: str) -> str:
    text = re.sub(_EMAIL, "[email]", text)
    text = re.sub(_CARD, "[card]", text)   # cards before phones (longer digit runs)
    text = re.sub(_PHONE, "[phone]", text)
    return text


def validate_listing_specs(specs: ListingSpecs) -> list[str]:
    """Value/sanity checks beyond the type schema. Returns a list of problems."""
    errors = []
    if specs.category is not None and specs.category not in KNOWN_CATEGORIES:
        errors.append("category unknown")
    if specs.condition not in _VALID_CONDITIONS:
        errors.append("condition invalid")
    return errors


class AuditLog:
    """Append-only record of actions — what to show an auditor (or yourself)."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, action: str, **meta) -> dict:
        entry = {"action": action, **meta}
        self.entries.append(entry)
        return entry
