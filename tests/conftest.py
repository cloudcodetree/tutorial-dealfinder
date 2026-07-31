"""Keep the suite deterministic regardless of the developer's .env.

dealfinder/__init__ loads .env on import, which is right for the app but wrong
for tests: several code paths branch on key presence (llm_extract falls back
to rule_extract, sources report available()), and the suite pins the offline,
deterministic behavior. Strip the keys here so a filled-in .env can't flip
those branches. Set LIVE_TESTS=1 to keep your keys (used by the opt-in
@pytest.mark.live smoke tests).
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
]


@pytest.fixture(autouse=True)
def _offline_keys(monkeypatch):
    if not os.getenv("LIVE_TESTS"):
        for k in _KEYS:
            monkeypatch.delenv(k, raising=False)
    yield
