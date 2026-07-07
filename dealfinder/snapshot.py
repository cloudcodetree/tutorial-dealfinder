"""Load the frozen real-electronics snapshot — the course's reproducible corpus.

Everything the ML parts train on, every quoted metric, and every offline test
reads from ONE committed, dated file: ``data/snapshots/electronics-2026-07.json``
(270 real listings pulled from the live aggregator). The live aggregator still
runs live in the parts that are *about* liveness; this module is the stable,
offline half of the snapshot/live split (spec §2).

A snapshot row is a flat dict::

    {id, query, category, title, brand, price, currency, source,
     marketplace, url, image_url, deal_pct, median_price_at_capture}

Note that ``brand`` here holds the *retailer* in 154/270 rows ("Walmart - COWIN",
"Target"); the true manufacturer is extracted from the title in ``features.py``.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from .schema import Product

# Repo-root-relative default location of the committed snapshots.
_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def _newest_snapshot() -> Path:
    """The lexically-newest ``electronics-*.json`` (dates sort correctly)."""
    matches = sorted(glob.glob(str(_SNAPSHOT_DIR / "electronics-*.json")))
    if not matches:
        raise FileNotFoundError(f"no electronics-*.json snapshot under {_SNAPSHOT_DIR}")
    return Path(matches[-1])


def load_snapshot(path: str | None = None) -> list[dict]:
    """Return the snapshot's raw item rows (list of dicts), newest file by default.

    Pass ``path`` to pin a specific snapshot (tests/eval that quote fixed numbers
    should pin the file so the numbers never drift).
    """
    p = Path(path) if path else _newest_snapshot()
    data = json.loads(p.read_text())
    # The snapshot is ``{"meta": {...}, "items": [...]}``; tolerate a bare list too.
    return data["items"] if isinstance(data, dict) else data


def load_snapshot_meta(path: str | None = None) -> dict:
    """Return the snapshot's ``meta`` block (created_at, per_query medians, …)."""
    p = Path(path) if path else _newest_snapshot()
    data = json.loads(p.read_text())
    return data.get("meta", {}) if isinstance(data, dict) else {}


def to_products(items: list[dict]) -> list[Product]:
    """Map snapshot rows to the normalized ``Product`` schema.

    Condition is parsed from the title here so the whole downstream pipeline
    (features, model, deal score) sees a populated ``Product.condition``.
    """
    from .features import parse_condition  # local import avoids a cycle

    products: list[Product] = []
    for r in items:
        products.append(
            Product(
                id=r["id"],
                title=r["title"],
                brand=r.get("brand"),
                category=r["category"],
                price=float(r["price"]),
                currency=r.get("currency", "USD"),
                url=r["url"],
                source=r.get("source", r.get("marketplace", "snapshot")),
                image_url=r.get("image_url"),
                marketplace=r.get("marketplace"),
                condition=parse_condition(r["title"]),
            )
        )
    return products


def load_products(path: str | None = None) -> list[Product]:
    """Convenience: snapshot file → list of ``Product`` in one call."""
    return to_products(load_snapshot(path))


# Allow overriding the default snapshot for tests/CI without touching callers.
_ENV_OVERRIDE = os.environ.get("DEALFINDER_SNAPSHOT")
if _ENV_OVERRIDE:  # pragma: no cover - convenience hook, not a tested path
    def _newest_snapshot() -> Path:  # type: ignore[no-redef]
        return Path(_ENV_OVERRIDE)
