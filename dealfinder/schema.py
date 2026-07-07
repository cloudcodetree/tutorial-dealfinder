"""The common normalized shape every connector produces and every later part consumes."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PricePoint(BaseModel):
    day: date
    price: float


class Product(BaseModel):
    id: str
    title: str
    brand: str | None
    category: str
    price: float
    currency: str = "USD"
    url: str
    source: str
    image_url: str | None = None
    # Broad-electronics fields (added for the real-data regeneration). All are
    # optional / defaulted so existing callers and fixtures keep working.
    marketplace: str | None = None  # e.g. "RapidAPI", "Apify" — where the offer was seen
    condition: str = "new"  # new / refurb / used (parsed from the title in features.py)
    specs: dict[str, str] = {}
    price_history: list[PricePoint] = []
