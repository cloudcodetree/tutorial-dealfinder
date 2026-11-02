"""Keep the suite deterministic regardless of the developer's .env.

dealfinder/__init__ loads .env on import, which is right for the app but wrong
for tests: sources report available() from key presence, and the suite pins the
offline, deterministic behavior. Strip the keys here so a filled-in .env can't
flip those branches. Set LIVE_TESTS=1 to keep your keys.
"""

import os

import pytest

_KEYS = [
    "RAPIDAPI_KEY",
    "OPENROUTER_API_KEY",
    "APIFY_TOKEN",
    "FIRECRAWL_API_KEY",
    "BESTBUY_API_KEY",
    "EBAY_APP_ID",
    "EBAY_CERT_ID",
    "EBAY_CAMPAIGN_ID",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_AI_TOKEN",
    "SENTRY_DSN",
    # Behavior switches, not keys, but a value in .env would flip the same branches.
    "DEALFINDER_SOURCES",
    "DEALFINDER_VERDICT_MODE",
    "DEALFINDER_EBAY_ALLOW_SANDBOX",
    "DEALFINDER_ENV",
]


@pytest.fixture(autouse=True)
def _offline_keys(monkeypatch):
    if not os.getenv("LIVE_TESTS"):
        for k in _KEYS:
            monkeypatch.delenv(k, raising=False)
    yield
