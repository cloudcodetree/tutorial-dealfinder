"""Connectors: each `DealSource` yields the same normalized `Product`, whatever the origin."""

from __future__ import annotations

import json
from typing import Iterator, Protocol, runtime_checkable

import httpx

from dealfinder.schema import PricePoint, Product


@runtime_checkable
class DealSource(Protocol):
    name: str

    def products(self) -> Iterator[Product]: ...


class DatasetSource:
    """Reproducible spine: a bundled dataset of products with price history."""

    name = "dataset"

    def __init__(self, path: str):
        self.path = path

    def products(self) -> Iterator[Product]:
        for r in json.loads(open(self.path).read()):
            yield Product(
                id=r["sku"],
                title=r["name"],
                brand=r.get("make"),
                category=r["cat"],
                price=r["usd"],
                url=r["link"],
                source=self.name,
                specs={k: str(r[k]) for k in ("weight_kg", "capacity") if k in r},
                price_history=[PricePoint(day=d, price=p) for d, p in r.get("history", [])],
            )


class ApiSource:
    """A live retail/price API behind the same interface (key-gated)."""

    name = "api"

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def products(self) -> Iterator[Product]:
        r = httpx.get(
            f"{self.base_url}/search",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        r.raise_for_status()
        for it in r.json()["items"]:
            yield Product(
                id=it["id"],
                title=it["title"],
                brand=it.get("brand"),
                category=it["category"],
                price=it["price"],
                url=it["url"],
                source=self.name,
            )
