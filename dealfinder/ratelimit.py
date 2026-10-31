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

import ipaddress
import os
import time
from collections.abc import Callable

from .compliance import SlidingWindowRateLimiter
from .settings import is_production

# A full cleanup scan runs at most this often per path, so a table that cannot be
# shrunk does not cost a scan on every request.
SHRINK_EVERY_S = 1.0

# path -> (requests, window seconds). The routes that can call an LLM are limited hardest:
# /ask, /ask_agentic, and /review, whose writer drafts with the LLM.
LIMITS: dict[str, tuple[int, float]] = {
    "/ask": (5, 60),
    "/ask_agentic": (5, 60),
    "/review": (5, 60),
    "/search": (30, 10),
    "/search/stream": (30, 10),
    "/check": (30, 10),
    "/ranked": (30, 10),
    "/semantic": (30, 10),
}


class Limiter:
    """One sliding window per limited path, keyed by `path|client`.

    Memory per path stays under max_keys after each cleanup and never passes
    2 * max_keys. Past that ceiling a new client waits one window while every
    client already tracked keeps its own count."""

    def __init__(self, limits: dict[str, tuple[int, float]] = LIMITS, *,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None:
        self._windows = {path: SlidingWindowRateLimiter(n, w) for path, (n, w) in limits.items()}
        self._clock = clock
        self.max_keys = max_keys
        self._last_shrink: dict[str, float] = {}

    def __len__(self) -> int:
        return sum(len(w._events) for w in self._windows.values())

    def check(self, path: str, client: str) -> float | None:
        """None when the request is allowed, else the seconds until it would be."""
        window = self._windows.get(path)
        if window is None:
            return None
        now = self._clock()
        key = f"{path}|{client}"
        events = window._events
        if key not in events and len(events) >= 2 * self.max_keys:
            self._maybe_shrink(path, window, now)
            if len(events) >= 2 * self.max_keys:
                return window.window
        allowed = window.allow(key, now)
        if len(events) > self.max_keys:
            self._maybe_shrink(path, window, now)
        if allowed:
            return None
        return events[key][0] + window.window - now

    def _maybe_shrink(self, path: str, window: SlidingWindowRateLimiter, now: float) -> None:
        if now - self._last_shrink.get(path, float("-inf")) >= SHRINK_EVERY_S:
            self._last_shrink[path] = now
            self._shrink(window, now)

    def _shrink(self, window: SlidingWindowRateLimiter, now: float) -> None:
        """Keep one path's clients under max_keys, even when every client is active.

        Each path has its own budget, so a flood on a cheap route cannot push out
        /ask state. Idle clients go first, then the least recently seen, down to
        90% of the cap so the next shrink waits for many new keys. A client at its
        limit is never evicted: forgetting it would reset its window, so a flood of
        new clients could buy the limited one a fresh allowance. Those keys leave on
        their own once their window passes."""
        idle = [k for k, ev in window._events.items() if not ev or ev[-1] <= now - window.window]
        for k in idle:
            del window._events[k]
        excess = len(window._events) - int(self.max_keys * 0.9)
        if excess <= 0:
            return
        open_keys = sorted((ev[-1], k) for k, ev in window._events.items() if len(ev) < window.limit)
        for _, k in open_keys[:excess]:
            del window._events[k]


def client_key(request) -> str:
    """Who a request counts against: the visitor's IP, or its /64 for IPv6.

    CF-Connecting-IP is trusted only when EDGE_SHARED_SECRET is set. Then the edge
    guard has already rejected any request that did not come through the Worker,
    which sets the header from the real visitor. Without the secret anyone could
    send the header, so the socket's address is used instead. One IPv6 subscriber
    usually holds a whole /64, so rotating addresses inside it buys nothing."""
    ip = request.headers.get("cf-connecting-ip") if os.getenv("EDGE_SHARED_SECRET") else None
    if not ip:
        ip = request.client.host if request.client else "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return ip


def enabled() -> bool:
    return is_production() or os.getenv("DEALFINDER_RATELIMIT") == "on"
