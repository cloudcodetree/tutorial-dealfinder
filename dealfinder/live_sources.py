"""Real, live deal sources behind the same DealSource interface (Part 1).

Each connector turns a real provider's response into our normalized `Product`.
Sources that need a key read it from the environment and simply sit out when it's
absent — so the app runs with whatever you've configured:

  - ItunesSource : keyless, real (Apple iTunes Search). Proves the pipeline today.
  - RapidApiSource: real cross-retailer prices (RapidAPI Real-Time Product Search).
                    Needs RAPIDAPI_KEY (free tier).
  - ApifySource  : real managed scraping (Apify actor). Needs APIFY_TOKEN (free
                    tier) and APIFY_ACTOR (defaults to a Google-Shopping actor).

Add a source = add a class. Nothing downstream changes.
"""
from __future__ import annotations

import base64
import os
import re
import time
from urllib.parse import urlparse

import httpx

from .schema import Product


def _f(v) -> float | None:
    try:
        return float(str(v).replace("$", "").replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        return None


class ItunesSource:
    name = "iTunes"
    # Media catalog — only a keyless fallback when no real retail source is set.
    fallback_only = True

    def available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 15) -> list[Product]:
        r = httpx.get("https://itunes.apple.com/search",
                      params={"term": query, "country": "US", "limit": limit}, timeout=15)
        out = []
        for it in r.json().get("results", []):
            price = _f(it.get("trackPrice") or it.get("collectionPrice"))
            if not price or price <= 0:
                continue
            tid = it.get("trackId") or it.get("collectionId")
            out.append(Product(
                id=f"itunes-{tid}",
                title=(it.get("trackName") or it.get("collectionName") or query)[:120],
                brand=it.get("artistName"), category=it.get("primaryGenreName", "media"),
                price=price, url=it.get("trackViewUrl") or it.get("collectionViewUrl") or "",
                source=self.name, image_url=it.get("artworkUrl100"),
            ))
        return out


class RapidApiSource:
    name = "RapidAPI"
    tier = 1  # fast, generous limits — try first
    _host = "real-time-product-search.p.rapidapi.com"

    def available(self) -> bool:
        return bool(os.getenv("RAPIDAPI_KEY"))

    def search(self, query: str, limit: int = 15) -> list[Product]:
        key = os.getenv("RAPIDAPI_KEY")
        if not key:
            return []
        r = httpx.get(f"https://{self._host}/search",
                      params={"q": query, "country": "us", "limit": str(limit)},
                      headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": self._host}, timeout=20)
        out = []
        for it in (r.json().get("data") or {}).get("products", []):
            price = _f(it.get("price"))
            if not price:
                continue
            store = it.get("store_name") or "store"
            out.append(Product(
                id=f"rapidapi-{str(it.get('product_id') or it.get('product_title', ''))[:40]}",
                title=(it.get("product_title") or query)[:120],
                brand=store, category="product", price=price,
                url=it.get("product_page_url") or "",
                source=f"{self.name}:{store}",
                image_url=(it.get("product_photos") or [None])[0],
            ))
        return out


class ApifySource:
    name = "Apify"
    tier = 2  # structured but costs credits / slower

    def available(self) -> bool:
        return bool(os.getenv("APIFY_TOKEN"))

    def search(self, query: str, limit: int = 15) -> list[Product]:
        token = os.getenv("APIFY_TOKEN")
        if not token:
            return []
        actor = os.getenv("APIFY_ACTOR", "automation-lab~google-shopping-scraper")
        r = httpx.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": token}, json={"queries": [query], "maxResults": limit}, timeout=180,
        )
        body = r.json()
        out = []
        for it in body if isinstance(body, list) else []:
            price = it.get("priceNumeric") or _f(it.get("price"))
            if not price:
                continue
            merchant = it.get("merchant") or "shopping"
            out.append(Product(
                id=f"apify-{(it.get('title') or '')[:40]}",
                title=(it.get("title") or query)[:120], brand=merchant,
                category="product", price=float(price),
                currency=it.get("currency") or "USD",
                url=it.get("productUrl") or "",
                source=f"{self.name}:{merchant}", image_url=it.get("imageUrl"),
            ))
        return out


class EbaySource:
    """eBay Browse API — official first-party search over live marketplace inventory
    (new + used/refurb), no scraping, no blocking. Adds resale deals the retail
    APIs miss. OAuth client-credentials with token caching; sandbox/prod chosen by
    the app id (…-SBX-… = sandbox) or EBAY_ENV. Set EBAY_CAMPAIGN_ID to earn
    affiliate commission via the returned affiliate URL."""

    name = "eBay"
    tier = 1  # official API, fast + reliable

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires = 0.0

    def _base(self) -> str:
        app = os.getenv("EBAY_APP_ID", "")
        sandbox = os.getenv("EBAY_ENV", "").lower() == "sandbox" or "SBX" in app
        return "https://api.sandbox.ebay.com" if sandbox else "https://api.ebay.com"

    def available(self) -> bool:
        return bool(os.getenv("EBAY_APP_ID") and os.getenv("EBAY_CERT_ID"))

    def _get_token(self) -> str:
        if self._token and time.monotonic() < self._expires:
            return self._token
        creds = f"{os.getenv('EBAY_APP_ID')}:{os.getenv('EBAY_CERT_ID')}"
        b64 = base64.b64encode(creds.encode()).decode()
        r = httpx.post(
            self._base() + "/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        self._token = j["access_token"]
        self._expires = time.monotonic() + j.get("expires_in", 7200) - 60
        return self._token

    def search(self, query: str, limit: int = 15) -> list[Product]:
        if not self.available():
            return []
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        campaign = os.getenv("EBAY_CAMPAIGN_ID")
        if campaign:  # affiliate attribution → itemAffiliateWebUrl in the response
            headers["X-EBAY-C-ENDUSERCTX"] = f"affiliateCampaignId={campaign}"
        r = httpx.get(
            self._base() + "/buy/browse/v1/item_summary/search",
            headers=headers, params={"q": query, "limit": str(limit)}, timeout=30,
        )
        if r.status_code != 200:
            return []
        out = []
        for it in (r.json().get("itemSummaries") or []):
            price = _f((it.get("price") or {}).get("value"))
            if not price:
                continue
            cond = it.get("condition") or "eBay"
            out.append(Product(
                id=f"ebay-{str(it.get('itemId', ''))[-40:]}",
                title=(it.get("title") or query)[:120], brand=None, category="product",
                price=price, currency=(it.get("price") or {}).get("currency", "USD"),
                url=it.get("itemAffiliateWebUrl") or it.get("itemWebUrl") or "",
                source=f"{self.name}:{cond}", image_url=(it.get("image") or {}).get("imageUrl"),
            ))
        return out


class ShopifySource:
    """Keyless, low-risk retail: most Shopify stores expose a public
    /products.json feed. Point it at stores relevant to your niche via
    SHOPIFY_STORES (comma-separated domains); we fetch the catalog and filter by
    query. Structured, generally unblocked, no anti-bot evasion."""

    name = "Shopify"
    tier = 3
    DEFAULT_STORES = ["deathwishcoffee.com", "www.allbirds.com", "www.kith.com"]

    def _stores(self) -> list[str]:
        env = os.getenv("SHOPIFY_STORES")
        return [s.strip() for s in env.split(",") if s.strip()] if env else self.DEFAULT_STORES

    def available(self) -> bool:
        return True  # keyless

    def search(self, query: str, limit: int = 15) -> list[Product]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
        out: list[Product] = []
        for store in self._stores():
            try:
                r = httpx.get(f"https://{store}/products.json", params={"limit": 250},
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
                if r.status_code != 200:
                    continue
                per_store = 0
                for p in r.json().get("products", []):
                    tags = p.get("tags") or []
                    if isinstance(tags, str):
                        tags = tags.split(",")
                    hay = f"{p.get('title', '')} {p.get('product_type', '')} {' '.join(tags)}".lower()
                    if tokens and not all(t in hay for t in tokens):
                        continue
                    v = (p.get("variants") or [{}])[0]
                    price = _f(v.get("price"))
                    if not price:
                        continue
                    imgs = p.get("images") or []
                    out.append(Product(
                        id=f"shopify-{store}-{p.get('id')}", title=(p.get("title") or query)[:120],
                        brand=p.get("vendor"), category="product", price=price,
                        url=f"https://{store}/products/{p.get('handle', '')}",
                        source=f"{self.name}:{store}",
                        image_url=(imgs[0].get("src") if imgs else None),
                    ))
                    per_store += 1
                    if per_store >= limit:
                        break
            except Exception:
                continue
        return out


class FirecrawlSource:
    """Broad-web source via Firecrawl search: catches long-tail retailers the
    structured shopping APIs miss. Noisier (page-level, not product-level), so we
    keep only results that carry a real price. Needs FIRECRAWL_API_KEY."""

    name = "Firecrawl"
    tier = 3  # broad-web, rate-limited — escalate to only if needed
    # editorial / review domains that quote prices but aren't a place to buy
    _SKIP = {"rtings.com", "nytimes.com", "techradar.com", "cnet.com", "tomsguide.com",
             "wired.com", "theverge.com", "pcmag.com", "forbes.com", "reddit.com",
             "youtube.com", "wikipedia.org", "wirecutter.com", "businessinsider.com"}

    def available(self) -> bool:
        return bool(os.getenv("FIRECRAWL_API_KEY"))

    def search(self, query: str, limit: int = 10) -> list[Product]:
        key = os.getenv("FIRECRAWL_API_KEY")
        if not key:
            return []
        r = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": f"{query} buy price", "limit": limit},
            timeout=60,
        )
        out = []
        for it in (r.json().get("data") or []):
            m = re.search(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)", it.get("description") or "")
            price = _f(m.group(1)) if m else None
            if not price or not (1 <= price <= 100000):
                continue
            dom = urlparse(it.get("url") or "").netloc.replace("www.", "") or "web"
            if dom in self._SKIP:
                continue
            out.append(Product(
                id=f"firecrawl-{(it.get('url') or it.get('title') or '')[:60]}",
                title=(it.get("title") or query)[:120], brand=dom, category="product",
                price=price, url=it.get("url") or "", source=f"{self.name}:{dom}", image_url=None,
            ))
        return out


LIVE_SOURCES = [EbaySource(), RapidApiSource(), ApifySource(), ShopifySource(), FirecrawlSource(), ItunesSource()]
