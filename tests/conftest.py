"""Keep the suite deterministic regardless of the developer's .env.

dealfinder/__init__ loads .env on import, which is right for the app but wrong
for tests: several code paths branch on key presence (llm_extract falls back
to rule_extract, sources report available()), and the suite pins the offline,
deterministic behavior. Strip the keys here so a filled-in .env can't flip
those branches. Set LIVE_TESTS=1 to keep your keys (used by the opt-in
@pytest.mark.live smoke tests).
"""

import os
import time

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from dealfinder import pgstore

_KEYS = [
    "RAPIDAPI_KEY",
    "OPENROUTER_API_KEY",
    "APIFY_TOKEN",
    "FIRECRAWL_API_KEY",
    "BESTBUY_API_KEY",
    "EBAY_APP_ID",
    "EBAY_CERT_ID",
    "EBAY_CAMPAIGN_ID",
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


@pytest.fixture
def db():
    """A migrated database URL for DB tests; skips when none is reachable.

    Offline runs (no DATABASE_URL) skip every DB test, so the suite stays green
    without Postgres. CI sets DATABASE_URL to a pgvector service, so they run."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    from dealfinder import migrate

    try:
        migrate.apply(url)
    except Exception as e:  # unreachable DB in this environment
        pytest.skip(f"db unavailable: {e}")
    return url


TEST_SUPABASE_URL = "https://demo-ref.supabase.co"


def bearer(token: str) -> dict:
    """Authorization header for a token."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def _es256_key():
    """One P-256 key per test session: the stand-in for Supabase's signing key."""
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def mint(_es256_key, monkeypatch):
    """Mint ES256 tokens the way Supabase Auth does, verified offline.

    Points SUPABASE_URL at a demo project and registers the session key's public
    JWK (kid "test-kid") with auth.set_jwks_for_testing, so the real verifier runs
    with no network. Teardown restores network fetching."""
    from dealfinder import auth

    monkeypatch.setenv("SUPABASE_URL", TEST_SUPABASE_URL)
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(_es256_key.public_key(), as_dict=True)
    auth.set_jwks_for_testing({"keys": [{**jwk, "kid": "test-kid", "alg": "ES256", "use": "sig"}]})

    def _mint(sub: str = "user-123", *, exp_delta: int = 3600, iss: str | None = None,
              aud: str = "authenticated", kid: str = "test-kid", **claims) -> str:
        now = int(time.time())
        body = {"sub": sub, "aud": aud, "iss": iss or f"{TEST_SUPABASE_URL}/auth/v1",
                "iat": now, "exp": now + exp_delta, **claims}
        return jwt.encode(body, _es256_key, algorithm="ES256", headers={"kid": kid})

    yield _mint
    auth.set_jwks_for_testing(None)


@pytest.fixture
def stub_sources(monkeypatch):
    """Keep /ranked off the network: canned Best Buy offers and deterministic embeddings."""
    from dealfinder import serve, shop

    fake = {
        "query": "x", "sources_live": ["Stub"], "throttled": [], "median_price": 60.0, "count": 3,
        "results": [
            {"id": "h1", "title": "Sony WH-1000XM5 Wireless Headphones", "brand": "Sony",
             "price": 50.0, "source": "BestBuy", "url": "", "image_url": None, "deal_pct": 16.7},
            {"id": "h2", "title": "Anker Soundcore Q20i Headphones", "brand": "Anker",
             "price": 60.0, "source": "BestBuy", "url": "", "image_url": None, "deal_pct": 0.0},
            {"id": "h3", "title": "Bose QuietComfort 45 Headphones", "brand": "Bose",
             "price": 70.0, "source": "BestBuy", "url": "", "image_url": None, "deal_pct": -16.7},
        ],
    }
    monkeypatch.setattr(serve, "aggregate", lambda q: fake)
    monkeypatch.setattr(shop, "_embed_texts", lambda titles: [[1.0, 0.0] for _ in titles])
    return fake


def row(id, title, price, source, **kw):
    """One aggregate result dict, as dealfinder.aggregate returns it."""
    return {"id": id, "title": title, "brand": None, "price": price, "source": source, "url": "",
            "image_url": None, "sku": None, "regular_price": None,
            "fetched_at": "2026-10-26T12:00:00Z", **kw}


_OFFER_IDS = ("off-1", "off-2", "acme-1", "bestbuy-77", "ebay-legacy")


@pytest.fixture
def offers(db):
    """Three catalog offers (two public, one in tenant acme); removes everything the tests made."""
    pgstore.upsert([{"id": "off-1", "title": "Anker Soundcore Q20i", "source": "BestBuy", "price": 44.99},
                    {"id": "off-2", "title": "Bose QuietComfort 45", "source": "BestBuy", "price": 46.00}],
                   None, tenant="public", url=db)
    pgstore.upsert([{"id": "acme-1", "title": "Acme Only", "source": "BestBuy", "price": 10.0}],
                   None, tenant="acme", url=db)
    yield db
    with psycopg.connect(db) as c:
        c.execute("delete from dealfinder.watchlist where offer_id = any(%s)", (list(_OFFER_IDS) + ["nope"],))
        c.execute("delete from dealfinder.offers where id = any(%s)", (list(_OFFER_IDS),))
