"""Per-instance rate limits for the anonymous routes.

The Cloudflare zone rule (30 per 10 s on `/api/search`) and the deals Worker's
limiters sit in front of these. This layer covers the routes they miss and is
the floor if someone reaches Cloud Run directly. It is per instance by design:
Cloud Run caps the service at 2 instances, so a client gets at most twice the
limit, and nothing shared has to exist.

It reuses Part 25's sliding window (`compliance.SlidingWindowRateLimiter`), one
window per limited path.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from .compliance import SlidingWindowRateLimiter
from .settings import is_production

# path -> (requests, window seconds). /ask calls an LLM, so it is limited hardest.
LIMITS: dict[str, tuple[int, float]] = {
    "/ask": (5, 60),
    "/ask_agentic": (5, 60),
    "/search": (30, 10),
    "/search/stream": (30, 10),
    "/check": (30, 10),
    "/ranked": (30, 10),
    "/semantic": (30, 10),
}


class Limiter:
    """One sliding window per limited path, keyed by `path|client`."""

    def __init__(self, limits: dict[str, tuple[int, float]] = LIMITS, *,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None:
        self._windows = {path: SlidingWindowRateLimiter(n, w) for path, (n, w) in limits.items()}
        self._clock = clock
        self.max_keys = max_keys

    def __len__(self) -> int:
        return sum(len(w._events) for w in self._windows.values())

    def check(self, path: str, client: str) -> float | None:
        """None when the request is allowed, else the seconds until it would be."""
        window = self._windows.get(path)
        if window is None:
            return None
        now = self._clock()
        key = f"{path}|{client}"
        if window.allow(key, now):
            if len(self) > self.max_keys:
                self._drop_idle(now)
            return None
        return window._events[key][0] + window.window - now

    def _drop_idle(self, now: float) -> None:
        """Forget every client with no request inside its window, so memory stays bounded."""
        for window in self._windows.values():
            idle = [k for k, ev in window._events.items() if not ev or ev[-1] <= now - window.window]
            for k in idle:
                del window._events[k]


def client_key(request) -> str:
    """The visitor's IP. The Worker sets CF-Connecting-IP from the real visitor, and the
    edge guard has already rejected any request that did not come through the Worker."""
    ip = request.headers.get("cf-connecting-ip")
    if ip:
        return ip
    return request.client.host if request.client else "unknown"


def enabled() -> bool:
    return is_production() or os.getenv("DEALFINDER_RATELIMIT") == "on"
