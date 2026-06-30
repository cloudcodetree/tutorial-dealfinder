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

import os
import re
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


class FirecrawlSource:
    """Broad-web source via Firecrawl search: catches long-tail retailers the
    structured shopping APIs miss. Noisier (page-level, not product-level), so we
    keep only results that carry a real price. Needs FIRECRAWL_API_KEY."""

    name = "Firecrawl"
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


LIVE_SOURCES = [ItunesSource(), RapidApiSource(), ApifySource(), FirecrawlSource()]
