"""Security & compliance at scale (Part 35) — EXTENDS Part 25's ``safety.py``.

Part 25 (``safety.py``) owns the *single-request* model surface: prompt-injection
detection, PII redaction, output validation, the audit log. This module does NOT
re-implement any of that (spec §9.8) — it **imports and builds on it** for the
*multi-tenant / at-scale* concerns a real SaaS has to answer:

- :class:`SlidingWindowRateLimiter` — per-user request throttling over a
  deterministic, injected clock (no wall-clock flakiness).
- :class:`DataSubjectStore` — GDPR data-subject helpers: **export** and **delete**
  a user's records from an in-memory store, every action written to Part 25's
  :class:`~dealfinder.safety.AuditLog`.
- :class:`AbuseDetector` — velocity + repeated-injection abuse detection, reusing
  Part 25's :func:`~dealfinder.safety.detect_prompt_injection` for the injection
  half (extends, doesn't reinvent).

Everything is deterministic and offline: the clock is injected, there is no
network, and the audit trail is inspectable.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

# EXTENDS Part 25: reuse its audit log and injection detector rather than
# re-implementing them (spec §9.8).
from .safety import AuditLog, detect_prompt_injection


# ---------------------------------------------------------------------------
# Sliding-window rate limiting (per user, injected clock).
# ---------------------------------------------------------------------------
class SlidingWindowRateLimiter:
    """Allow up to ``limit`` requests per ``window`` seconds, per user.

    A true sliding window (not a fixed bucket): each user keeps a deque of recent
    request timestamps; on each call we evict anything older than ``now - window``
    and allow the request only if fewer than ``limit`` remain. The clock is passed
    in to :meth:`allow`, so behavior is fully deterministic and testable — no
    ``time.time()``.
    """

    def __init__(self, limit: int, window: float) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self.window = float(window)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, user_id: str, now: float) -> bool:
        """Return True and record the request if the user is under the limit."""
        events = self._events[user_id]
        cutoff = now - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True

    def remaining(self, user_id: str, now: float) -> int:
        """How many requests the user could still make at time ``now``."""
        events = self._events[user_id]
        cutoff = now - self.window
        active = sum(1 for t in events if t > cutoff)
        return max(0, self.limit - active)


# ---------------------------------------------------------------------------
# GDPR data-subject requests (export + delete), audited via Part 25's AuditLog.
# ---------------------------------------------------------------------------
@dataclass
class DataSubjectStore:
    """A minimal per-user record store with GDPR export/delete, fully audited.

    Stands in for the tables that hold a user's data (saved searches, history,
    notifications). ``export`` satisfies a Subject Access Request; ``delete``
    satisfies the Right to Erasure. Both write to Part 25's :class:`AuditLog` so
    there's a compliance trail (extends, does not re-implement — spec §9.8).
    """

    audit: AuditLog = field(default_factory=AuditLog)
    _records: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))

    def add(self, user_id: str, record: dict) -> None:
        self._records[user_id].append(record)

    def export(self, user_id: str) -> list[dict]:
        """Return a copy of every record held for a user (a SAR), and audit it."""
        records = [dict(r) for r in self._records.get(user_id, [])]
        self.audit.record("gdpr_export", user_id=user_id, count=len(records))
        return records

    def delete(self, user_id: str) -> int:
        """Erase all of a user's records; return how many were removed, audited."""
        removed = len(self._records.get(user_id, []))
        self._records.pop(user_id, None)
        self.audit.record("gdpr_delete", user_id=user_id, count=removed)
        return removed

    def count(self, user_id: str) -> int:
        return len(self._records.get(user_id, []))


# ---------------------------------------------------------------------------
# Abuse detection (velocity + repeated injection), reusing Part 25's detector.
# ---------------------------------------------------------------------------
@dataclass
class AbuseSignal:
    """The verdict for one user, with the reasons it fired."""

    user_id: str
    flagged: bool
    reasons: list[str] = field(default_factory=list)


class AbuseDetector:
    """Flag abusive users by request velocity and repeated injection attempts.

    - **velocity**: more than ``max_events`` requests within ``window`` seconds.
    - **injection**: at least ``max_injections`` prompt-injection attempts (each
      classified by Part 25's :func:`detect_prompt_injection`) in the window.

    Deterministic: timestamps are supplied by the caller. This *extends* Part 25 —
    Part 25 answers "is THIS request an injection?"; this answers "is this USER,
    across many requests, abusing the system?".
    """

    def __init__(
        self,
        *,
        window: float = 60.0,
        max_events: int = 20,
        max_injections: int = 3,
    ) -> None:
        self.window = float(window)
        self.max_events = max_events
        self.max_injections = max_injections
        self._events: dict[str, deque[tuple[float, bool]]] = defaultdict(deque)

    def observe(self, user_id: str, text: str, now: float) -> AbuseSignal:
        """Record one request (text + time) and report the current abuse verdict."""
        is_injection = detect_prompt_injection(text)  # Part 25 does the per-text call
        events = self._events[user_id]
        events.append((now, is_injection))

        cutoff = now - self.window
        while events and events[0][0] <= cutoff:
            events.popleft()

        reasons: list[str] = []
        if len(events) > self.max_events:
            reasons.append(f"velocity: {len(events)} requests in {self.window:.0f}s")
        injections = sum(1 for _, inj in events if inj)
        if injections >= self.max_injections:
            reasons.append(f"injection: {injections} attempts in {self.window:.0f}s")

        return AbuseSignal(user_id=user_id, flagged=bool(reasons), reasons=reasons)
