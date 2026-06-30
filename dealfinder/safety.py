"""Guardrails: the boring-but-hireable layer that keeps an AI system safe.

Defense in depth — never trust input, never trust model output, and log
everything:
  - detect_prompt_injection: flag user text trying to hijack instructions.
  - redact_pii: strip emails / phones / cards before logging or prompting.
  - validate_listing_specs: range checks beyond type (a schema says int; this
    says a sane int).
  - AuditLog: a tamper-evident-ish trail of who did what.
"""
from __future__ import annotations

import re

from .extract import ListingSpecs

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
    """Range/sanity checks beyond the type schema. Returns a list of problems."""
    errors = []
    if specs.capacity is not None and not (1 <= specs.capacity <= 12):
        errors.append("capacity out of range")
    if specs.weight_kg is not None and not (0 < specs.weight_kg < 50):
        errors.append("weight_kg out of range")
    if specs.season is not None and specs.season not in (1, 2, 3, 4):
        errors.append("season invalid")
    return errors


class AuditLog:
    """Append-only record of actions — what to show an auditor (or yourself)."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, action: str, **meta) -> dict:
        entry = {"action": action, **meta}
        self.entries.append(entry)
        return entry
