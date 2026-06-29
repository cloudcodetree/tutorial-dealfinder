"""One-command pipeline: pull from sources -> dedup -> persist to SQLite.

Add the API/scraper sources here too once you have keys/fixtures; the dataset is
the reproducible default.
"""

from __future__ import annotations

from dealfinder.ingest import ingest
from dealfinder.sources import DatasetSource
from dealfinder.store import save

if __name__ == "__main__":
    products = ingest([DatasetSource("data/sample/products.json")])
    n = save(products, "dealfinder.sqlite")
    print(f"ingested {len(products)} products -> dealfinder.sqlite ({n} rows)")
