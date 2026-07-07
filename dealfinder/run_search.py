"""Search the catalog four ways and show how each stage changes the results.

Runs over the real snapshot with the cached title embeddings; the "noise
cancelling headphones" query surfaces the hero cast, and the value rerank blends
in the two-signal deal score so the honest Anker Q20i rises above the Bose-QC45
trap.

Run:  python -m dealfinder.run_search
"""
from __future__ import annotations

import json
from pathlib import Path

from .embed import embed_texts, product_text
from .recommend import load_catalog_embeddings
from .search import BM25, cosine_rank, rrf_fuse, search_catalog
from .snapshot import load_products

QUERY = "noise cancelling headphones"
K = 5


def main() -> None:
    d = json.loads(Path("data/snapshots/electronics-2026-07.json").read_text())
    nch_ids = {i["id"] for i in d["items"] if i["query"] == QUERY}
    medians = {i["id"]: i["median_price_at_capture"] for i in d["items"]}

    catalog = [p for p in load_products() if p.id in nch_ids]
    _, emb = load_catalog_embeddings(catalog)
    texts = [product_text(p) for p in catalog]

    def show(label, ids):
        print(f"\n{label}:")
        for i in ids[:K]:
            print(f"  {catalog[i].title[:44]:44} ${catalog[i].price:>7.2f}")

    qv = embed_texts([QUERY])[0]
    semantic = [i for i, _ in cosine_rank(qv, emb, K)]
    keyword = [i for i, _ in BM25(texts).search(QUERY, K)]
    hybrid = rrf_fuse([semantic, keyword], top=K)

    print(f'query: "{QUERY}"')
    show("semantic (meaning)", semantic)
    show("keyword (BM25)", keyword)
    show("hybrid (RRF fusion)", hybrid)

    print("\nreranked by value (relevance + two-signal deal score):")
    for _, p, deal in search_catalog(QUERY, catalog, emb, medians, k=K):
        print(f"  {p.title[:44]:44} ${p.price:>7.2f}  (deal {deal:+.2f})")


if __name__ == "__main__":
    main()
