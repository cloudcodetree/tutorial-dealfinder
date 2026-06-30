import numpy as np

from dealfinder.search import BM25, cosine_rank, rrf_fuse, value_rerank


def test_cosine_rank_orders_by_similarity():
    docs = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])
    q = np.array([1.0, 0.0])
    ranked = [i for i, _ in cosine_rank(q, docs, k=3)]
    assert ranked[0] == 0 and ranked[1] == 1 and ranked[2] == 2


def test_bm25_finds_keyword_docs_only():
    docs = ["ultralight backpacking tent", "noise cancelling headphones", "family camping tent"]
    hits = [i for i, _ in BM25(docs).search("tent", k=3)]
    assert set(hits) == {0, 2}  # both tents, not the headphones


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
