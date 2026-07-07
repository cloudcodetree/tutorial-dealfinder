"""The evaluation harness on the frozen snapshot golden set (spec §9.4).

Deterministic/offline: the golden set is 20 hand-labeled real items and both
rankers are fit on the committed snapshot. The load-bearing assertions are that
the two-signal ranker clears the ``precision@5 >= 0.80`` gate while the naive
median-only ranker (fooled by the too-good-to-be-true traps) does not.
"""
from collections import Counter

from dealfinder.evals import (
    GATE_PRECISION,
    ab_compare,
    evaluate,
    load_golden,
    median_only_ranker,
    two_signal_ranker,
)


def test_golden_set_is_20_labeled_snapshot_items():
    golden = load_golden()
    assert len(golden) == 20
    # all 15 headphones + 5 cross-category
    headphones = [g for g in golden if "headphone" in g["title"].lower()]
    assert len(headphones) >= 13  # the anchor subset (some titles omit the word)
    labels = Counter(g["label"] for g in golden)
    assert set(labels) <= {"deal", "fair", "suspicious", "overpriced"}
    assert labels["deal"] == 6


def test_two_signal_ranker_passes_the_eval_gate():
    report = evaluate(two_signal_ranker)
    assert report["n"] == 20
    assert report["precision_at_5"] >= GATE_PRECISION
    assert report["passes_gate"]
    # every one of its top-5 is a genuine deal
    assert all(t["label"] == "deal" for t in report["top5"])


def test_median_only_ranker_is_fooled_and_misses_the_gate():
    report = evaluate(median_only_ranker)
    assert report["precision_at_5"] < GATE_PRECISION
    # the naive signal surfaces the trap listings in its top-5
    assert any(t["label"] == "suspicious" for t in report["top5"])


def test_ab_compare_prefers_the_two_signal_ranker():
    a = evaluate(two_signal_ranker)["precision_at_5"]
    b = evaluate(median_only_ranker)["precision_at_5"]
    res = ab_compare("two_signal", a, "median_only", b)
    assert res["winner"] == "two_signal"
    assert res["delta"] > 0
