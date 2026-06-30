import math

from dealfinder.ranking import ndcg_at_k, precision_at_k, recall_at_k


def test_precision_and_recall_at_k():
    rec = ["a", "b", "c", "d"]
    relevant = {"b", "d"}
    assert precision_at_k(rec, relevant, k=2) == 0.5   # ['a','b'] → 1 hit / 2
    assert recall_at_k(rec, relevant, k=2) == 0.5      # 1 of 2 relevant found


def test_ndcg_rewards_rank_order():
    # a relevant item at rank 2 scores less than at rank 1
    relevant = {"b"}
    top1 = ndcg_at_k(["b", "a"], relevant, k=2)
    top2 = ndcg_at_k(["a", "b"], relevant, k=2)
    assert top1 == 1.0
    assert math.isclose(top2, 1 / math.log2(3), rel_tol=1e-9)
    assert top1 > top2


def test_ndcg_zero_when_nothing_relevant():
    assert ndcg_at_k(["a", "b"], {"z"}, k=2) == 0.0
