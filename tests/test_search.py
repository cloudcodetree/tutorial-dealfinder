import numpy as np

from dealfinder.search import BM25, cosine_rank, rrf_fuse, value_rerank


def test_cosine_rank_orders_by_similarity():
    docs = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])
    q = np.array([1.0, 0.0])
    ranked = [i for i, _ in cosine_rank(q, docs, k=3)]
    assert ranked[0] == 0 and ranked[1] == 1 and ranked[2] == 2


def test_bm25_finds_keyword_docs_only():
    docs = ["noise cancelling headphones", "mechanical gaming keyboard", "wireless earbuds"]
    hits = [i for i, _ in BM25(docs).search("headphones", k=3)]
    assert hits == [0]  # only the headphones doc has the term


def test_rrf_rewards_top_in_both_lists():
    # doc 0 is near the top of both retrievers; doc 3 is bottom of both.
    fused = rrf_fuse([[0, 1, 2, 3], [0, 2, 1, 3]])
    assert fused[0] == 0   # high in both → wins
    assert fused[-1] == 3  # low in both → loses


def test_value_rerank_promotes_better_deal():
    # same retrieval order, but B is a strong deal → should rise above C
    order = ["A", "B", "C"]
    deal = {"A": 0.0, "B": 0.4, "C": 0.0}
    reranked = value_rerank(order, deal, alpha=0.6)
    assert reranked.index("B") < reranked.index("C")


def test_search_catalog_surfaces_hero_cast_and_rewards_the_honest_deal():
    """'noise cancelling headphones' → hero cast; value rerank floats the Anker
    Q20i above the Bose-QC45 trap."""
    import json

    from dealfinder.recommend import load_catalog_embeddings
    from dealfinder.search import search_catalog
    from dealfinder.snapshot import load_products

    d = json.load(open("data/snapshots/electronics-2026-07.json"))
    nch_ids = {i["id"] for i in d["items"] if i["query"] == "noise cancelling headphones"}
    medians = {i["id"]: i["median_price_at_capture"] for i in d["items"]}

    products = [p for p in load_products() if p.id in nch_ids]
    _, emb = load_catalog_embeddings(products)
    results = search_catalog("noise cancelling headphones", products, emb, medians, k=5)

    titles = [p.title for _, p, _ in results]
    # the top hit is the honest Anker Q20i deal
    assert "Anker Soundcore Q20i" in titles[0]
    # the Bose QC45 trap, if surfaced at all, ranks below the Anker (deal < 0)
    anker_deal = results[0][2]
    assert anker_deal > 0
    bose = [ds for _, p, ds in results if "QuietComfort 45" in p.title]
    assert all(ds < anker_deal for ds in bose)
