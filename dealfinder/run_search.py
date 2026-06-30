"""Search the catalog four ways and show how each stage changes the results.

Run:  python -m dealfinder.run_search
"""
from __future__ import annotations

import json
from pathlib import Path

from .deal import deal_score
from .dealmodel import LinearModel
from .embed import embed_texts, product_text
from .features import feature_matrix
from .schema import Product
from .search import BM25, cosine_rank, rrf_fuse, value_rerank

QUERY = "ultralight 2-person tent for backpacking"
K = 5


def main() -> None:
    catalog = [Product.model_validate(r) for r in json.loads(Path("data/sample/catalog.json").read_text())]
    texts = [product_text(p) for p in catalog]

    # deal score per index, from the Part-3 price model
    X = feature_matrix(catalog)
    model = LinearModel().fit(X, [p.price for p in catalog])
    fair = model.predict(X)
    deal = {i: deal_score(catalog[i].price, fair[i]) for i in range(len(catalog))}

    def show(label, ids):
        print(f"\n{label}:")
        for i in ids[:K]:
            pct = deal[i] * 100
            tag = f"{abs(pct):.0f}% {'under' if pct >= 0 else 'over'} fair"
            print(f"  {catalog[i].id}: {catalog[i].title:<24} ${catalog[i].price:>6.0f}  ({tag})")

    doc_vecs = embed_texts(texts)
    qv = embed_texts([QUERY])[0]
    semantic = [i for i, _ in cosine_rank(qv, doc_vecs, K)]
    keyword = [i for i, _ in BM25(texts).search(QUERY, K)]
    hybrid = rrf_fuse([semantic, keyword], top=K)
    valued = value_rerank(hybrid, deal, alpha=0.5)

    print(f'query: "{QUERY}"')
    show("semantic (meaning)", semantic)
    show("keyword (BM25)", keyword)
    show("hybrid (RRF fusion)", hybrid)
    show("reranked by value (relevance + deal)", valued)


if __name__ == "__main__":
    main()
