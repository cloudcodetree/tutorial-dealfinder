"""Dataset engineering (Part 15): turn the frozen snapshot into a labeled,
leakage-safe training set — sampling, labeling, splitting, class imbalance.

This is the bridge between the raw corpus and the ML parts. It does three jobs a
real ML dataset has to do, and it does them against the ONE committed snapshot so
the numbers reproduce (spec §2, §5 reproducibility contract):

1. **Label** every listing with the two-signal verdict from ``dealscore`` — the
   same ``deal | fair | suspicious | overpriced`` labels the course uses
   everywhere — as the supervised target, with the §4 feature vector + cached
   title embeddings (spec §9.5) as X.
2. **Split without leakage.** Near-duplicate listings of the same product recur
   across sources and marketplaces (the Sony WH-1000XM5 shows up at $162.97 and
   $248, spec §9.6). A random row split would let a train row and its
   near-duplicate test row straddle the boundary and inflate the score. So we
   split by **query group** — every row for a given query lands on ONE side.
3. **Confront class imbalance honestly.** The label distribution is skewed
   (mostly ``overpriced``); we report the real counts and hand back sklearn-style
   **balanced class weights** so a classifier can compensate — no resampling
   magic, no fabricated balance.

Everything here is deterministic and offline. The labels come from the committed
snapshot via the same per-category linear price model the two-signal score uses
in ``evals.py``, so this dataset is consistent with the rest of the course.

A note on **temporal splits.** The right way to split a *price* dataset is by
time (train on the past, test on the future) so you never peek ahead. Our
snapshot is a single capture with **no ``price_history``** on the rows (it is
empty for all 270 — verify with ``load_snapshot``), so there is no real time axis
to split on yet. ``temporal_split`` is provided as the honest hook: it splits on
whatever ordering key you pass (e.g. a capture timestamp once the pipeline in
Part 16 records one), and its docstring says plainly that on *this* snapshot it
degrades to an index split. We do not pretend to a temporal split the data can't
support.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .dealmodel import LinearModel
from .dealscore import fair_price, verdict
from .features import feature_matrix, featurize
from .schema import Product
from .snapshot import load_products, load_snapshot

LABELS = ("deal", "fair", "suspicious", "overpriced")

# A category needs at least this many rows before we fit a per-category linear
# price model for it (mirrors ``evals.two_signal_ranker``). Smaller categories
# fall back to "fair price = market median", which yields a neutral verdict.
_MIN_CATEGORY_ROWS = 3


def _per_category_models(products: list[Product]) -> dict[str, LinearModel]:
    """Fit one linear price model per category with enough rows (matches evals.py)."""
    by_cat: dict[str, list[Product]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    return {
        c: LinearModel().fit(feature_matrix(ps), [p.price for p in ps])
        for c, ps in by_cat.items()
        if len(ps) >= _MIN_CATEGORY_ROWS
    }


def label_for(product: Product, median: float, models: dict[str, LinearModel]) -> str:
    """The two-signal verdict label for one listing (the supervised target).

    Uses the per-category linear fair price as the model guard; if the category is
    too small to model, the fair price falls back to the market median (so the
    residual guard is neutral and the label is driven by the median signal alone).
    """
    model = models.get(product.category)
    fair = fair_price(model, featurize(product)) if model is not None else median
    return verdict(product.price, median, fair).label


@dataclass
class LabeledDataset:
    """A leakage-aware labeled dataset built from the frozen snapshot.

    - ``X``            (n, d) features: the §4 hand vector, optionally concatenated
      with the cached title embedding (spec §9.5).
    - ``y``            (n,) integer label codes indexing ``LABELS``.
    - ``ids``          (n,) snapshot item ids, aligned to X/y.
    - ``queries``      (n,) the query each row belongs to — the grouping key that
      keeps near-duplicate listings of the same product on one side of a split.
    - ``feature_names`` column names for X (hand features first, then ``emb_k``).
    """

    X: np.ndarray
    y: np.ndarray
    ids: list[str]
    queries: list[str]
    feature_names: list[str] = field(default_factory=list)

    def label_names(self) -> list[str]:
        """The string label for each row (``LABELS[code]``)."""
        return [LABELS[c] for c in self.y]

    def label_distribution(self) -> dict[str, int]:
        """Real per-label counts over the whole dataset (the skew is the lesson)."""
        counts = Counter(self.label_names())
        return {lab: counts.get(lab, 0) for lab in LABELS}


def build_labeled_dataset(
    path: str | None = None,
    *,
    with_embeddings: bool = False,
) -> LabeledDataset:
    """Build the labeled "good deal" dataset from the committed snapshot.

    Label = the two-signal ``dealscore`` verdict (deal/fair/suspicious/overpriced).
    X = the §4 feature vector, plus the cached 384-dim title embedding when
    ``with_embeddings`` is set (spec §9.5 — the Part-4 cache, not a fresh run).

    Deterministic and offline: no network, no model download. Returns a
    :class:`LabeledDataset` aligned by snapshot id.
    """
    items = load_snapshot(path)
    products = load_products(path)
    by_id = {p.id: p for p in products}
    models = _per_category_models(products)

    ids: list[str] = []
    queries: list[str] = []
    y: list[int] = []
    hand_rows: list[list[float]] = []
    for r in items:
        p = by_id[r["id"]]
        median = float(r["median_price_at_capture"])
        label = label_for(p, median, models)
        ids.append(p.id)
        queries.append(r["query"])
        y.append(LABELS.index(label))
        hand_rows.append(featurize(p))

    X = np.asarray(hand_rows, dtype=float)
    feature_names = ["category_code", "brand_tier", "condition_code"]

    if with_embeddings:
        from .embed import load_title_embeddings

        emb_ids, vectors = load_title_embeddings()
        order = {i: k for k, i in enumerate(emb_ids)}
        emb = np.asarray([vectors[order[i]] for i in ids], dtype=float)
        X = np.hstack([X, emb])
        feature_names += [f"emb_{k}" for k in range(emb.shape[1])]

    return LabeledDataset(
        X=X, y=np.asarray(y, dtype=int), ids=ids, queries=queries,
        feature_names=feature_names,
    )


def grouped_split(
    queries: list[str],
    *,
    test_frac: float = 0.25,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Split row indices by **query group** so no query straddles train/test.

    Near-duplicate listings of the same product share a query; if some landed in
    train and their twins in test, the model would be graded on rows it has
    effectively already seen. Grouping by query removes that leakage: whole
    queries go to one side. Deterministic for a given ``seed``.

    Returns ``(train_idx, test_idx)`` — arrays of row positions into the aligned
    arrays. Guarantees at least one query on each side (when there are >= 2).
    """
    groups = list(dict.fromkeys(queries))  # unique queries, stable order
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(groups))
    n_test_groups = max(1, int(round(len(groups) * test_frac)))
    if len(groups) >= 2:
        n_test_groups = min(n_test_groups, len(groups) - 1)  # keep train non-empty
    test_groups = {groups[i] for i in order[:n_test_groups]}

    q = np.asarray(queries)
    test_idx = np.where(np.isin(q, list(test_groups)))[0]
    train_idx = np.where(~np.isin(q, list(test_groups)))[0]
    return train_idx, test_idx


def temporal_split(
    order_key: list | None = None,
    n: int | None = None,
    *,
    test_frac: float = 0.25,
) -> tuple[np.ndarray, np.ndarray]:
    """Train-on-past / test-on-future split — the honest hook (see module docstring).

    Pass ``order_key`` (e.g. a capture timestamp per row) and the last
    ``test_frac`` of rows *in that order* become the test set. The current
    snapshot rows carry **no ``price_history`` / capture time** (all empty), so
    there is no real time axis to split on; call this with an explicit
    ``order_key`` once the Part-16 pipeline records one. With no ``order_key`` it
    degrades to a plain index split over ``n`` rows and does NOT claim to be
    temporal — it is a placeholder so downstream code has a stable seam.
    """
    if order_key is not None:
        n = len(order_key)
        ranked = np.argsort(np.asarray(order_key), kind="stable")
    else:
        if n is None:
            raise ValueError("temporal_split needs either order_key or n")
        ranked = np.arange(n)
    n_test = max(1, int(round(n * test_frac)))
    return ranked[:-n_test], ranked[-n_test:]


def class_weights(y: np.ndarray) -> dict[int, float]:
    """Balanced class weights (sklearn's ``n / (n_classes * count)`` formula).

    The label distribution is skewed toward ``overpriced``; a classifier trained
    on raw counts would learn to shout "overpriced" and still look accurate. These
    weights up-weight the rare classes so the loss cares about ``deal`` and
    ``suspicious`` too — a simple, honest imbalance strategy (no resampling, no
    synthetic rows). Keys are label codes indexing :data:`LABELS`.
    """
    counts = Counter(int(c) for c in y)
    n = len(y)
    k = len(counts)
    return {code: n / (k * cnt) for code, cnt in sorted(counts.items())}


def imbalance_summary(ds: LabeledDataset) -> dict:
    """A compact report of the skew + the handling strategy (real numbers only)."""
    dist = ds.label_distribution()
    n = int(ds.y.shape[0])
    majority = max(dist, key=dist.get)
    return {
        "n": n,
        "counts": dist,
        "fractions": {lab: round(c / n, 4) for lab, c in dist.items()},
        "majority_class": majority,
        "majority_fraction": round(dist[majority] / n, 4),
        "class_weights": {LABELS[c]: round(w, 4) for c, w in class_weights(ds.y).items()},
        "strategy": (
            "balanced class weights (n / (n_classes * count)); no resampling — "
            "the skew is real and reported, not hidden"
        ),
    }
