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
    specs: dict[str, str] = {}
    price_history: list[PricePoint] = []
