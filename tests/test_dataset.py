"""Dataset engineering (Part 19) on the frozen snapshot.

Deterministic and offline: labels come from the committed snapshot via the same
two-signal deal score the rest of the course uses. The load-bearing assertions
pin the REAL (skewed) label distribution and prove the grouped split keeps every
query's rows on a single side (no train/test leakage of near-duplicates).
"""
import numpy as np

from dealfinder.dataset import (
    LABELS,
    build_labeled_dataset,
    class_weights,
    grouped_split,
    imbalance_summary,
)


def test_labeled_dataset_shapes_and_alignment():
    ds = build_labeled_dataset()
    n = ds.X.shape[0]
    assert n == 270  # every snapshot row is labeled
    assert ds.X.shape[1] == 3  # the §4 hand feature vector
    assert ds.feature_names == ["category_code", "brand_tier", "condition_code"]
    assert len(ds.ids) == n and len(ds.queries) == n and ds.y.shape[0] == n
    assert set(int(c) for c in ds.y) <= set(range(len(LABELS)))


def test_real_label_distribution_is_pinned():
    # The two-signal verdict as the label yields a skewed distribution — this is
    # the real, computed count, not a balanced fantasy. Pinning it guards the
    # reproducibility contract (spec §5): if the snapshot or scoring drifts, the
    # prose that quotes these counts must be updated too.
    ds = build_labeled_dataset()
    dist = ds.label_distribution()
    assert dist == {"deal": 71, "fair": 40, "suspicious": 32, "overpriced": 127}
    assert sum(dist.values()) == 270


def test_imbalance_summary_reports_real_skew_and_weights():
    ds = build_labeled_dataset()
    s = imbalance_summary(ds)
    assert s["n"] == 270
    assert s["majority_class"] == "overpriced"
    assert s["majority_fraction"] == 0.4704
    # balanced weights up-weight the rare classes (suspicious is rarest).
    w = s["class_weights"]
    assert w["suspicious"] > w["deal"] > w["overpriced"]
    assert "no resampling" in s["strategy"]


def test_class_weights_formula():
    # sklearn's balanced formula: n / (n_classes * count). Rarer class → bigger.
    y = np.array([0, 0, 0, 1])  # 3 of class 0, 1 of class 1
    w = class_weights(y)
    assert w[0] == 4 / (2 * 3)
    assert w[1] == 4 / (2 * 1)


def test_grouped_split_keeps_each_query_on_one_side():
    # The core anti-leakage guarantee: no query appears in BOTH train and test,
    # so near-duplicate listings of the same product can't straddle the boundary.
    ds = build_labeled_dataset()
    train_idx, test_idx = grouped_split(ds.queries, seed=0)

    q = np.asarray(ds.queries)
    train_queries = set(q[train_idx])
    test_queries = set(q[test_idx])
    assert train_queries.isdisjoint(test_queries)  # no query straddles

    # Partition is complete and non-overlapping.
    assert len(train_idx) + len(test_idx) == len(ds.queries)
    assert set(train_idx).isdisjoint(test_idx)
    # Both sides are non-empty.
    assert len(train_idx) > 0 and len(test_idx) > 0


def test_grouped_split_is_deterministic():
    ds = build_labeled_dataset()
    a = grouped_split(ds.queries, seed=0)
    b = grouped_split(ds.queries, seed=0)
    assert list(a[0]) == list(b[0]) and list(a[1]) == list(b[1])


def test_with_embeddings_appends_384_dims():
    ds = build_labeled_dataset(with_embeddings=True)
    assert ds.X.shape == (270, 3 + 384)
    assert ds.feature_names[:3] == ["category_code", "brand_tier", "condition_code"]
    assert ds.feature_names[3] == "emb_0" and ds.feature_names[-1] == "emb_383"
