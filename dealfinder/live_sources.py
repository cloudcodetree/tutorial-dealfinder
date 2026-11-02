"""Real, live deal sources behind the same DealSource interface (Part 1).

Each connector turns a real provider's response into our normalized `Product`.
Sources that need a key read it from the environment and simply sit out when it's
absent:

  - RapidApiSource: real cross-retailer prices (RapidAPI Real-Time Product Search).
                    Needs RAPIDAPI_KEY (free tier).
  - ApifySource  : real managed scraping (Apify actor). Needs APIFY_TOKEN and
                    DEALFINDER_ENABLE_PAID_SOURCES=1, because the actor is metered.

Add a source = add a class. Nothing downstream changes.
"""
from __future__ import annotations

import os

import httpx

from .schema import Product

def _f(v) -> float | None:
    try:
        return float(str(v).replace("$", "").replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        return None


def _paid_ok() -> bool:
    """Metered sources (Apify actors, Firecrawl) only run when explicitly opted in.

    Amazon has no free data path, and the Apify Google-Shopping/eBay actors are
    pay-per-event, so by default DealFinder runs on the free stack only (eBay
    Browse API, RapidAPI free tier, BestBuy, Shopify, iTunes) and never touches a
    metered service. Set DEALFINDER_ENABLE_PAID_SOURCES=1 to turn the paid ones on.
    """
    return os.getenv("DEALFINDER_ENABLE_PAID_SOURCES") == "1"



# ANCHOR: rapidapi-source
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
# ANCHOR_END: rapidapi-source


class ApifySource:
    name = "Apify"
    tier = 2  # structured but costs credits / slower
    metered = True  # the Apify Google-Shopping actor is pay-per-event

    def available(self) -> bool:
        return bool(os.getenv("APIFY_TOKEN")) and _paid_ok()

    def search(self, query: str, limit: int = 15) -> list[Product]:
        token = os.getenv("APIFY_TOKEN")
        if not token:
            return []
        actor = os.getenv("APIFY_ACTOR", "automation-lab~google-shopping-scraper")
        r = httpx.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": token},
            # country/language pin the marketplace: without them the actor mixes in
            # localized listings (Mercado Libre in MXN, etc.) whose prices would
            # masquerade as USD and poison the cross-source median.
            json={"queries": [query], "maxResults": limit, "country": "us", "language": "en"},
            timeout=180,
        )
        body = r.json()
        out = []
        for it in body if isinstance(body, list) else []:
            price = it.get("priceNumeric") or _f(it.get("price"))
            if not price:
                continue
            if (it.get("currency") or "USD").upper() != "USD":
                continue  # belt-and-braces: never let a foreign-currency price into USD math
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
