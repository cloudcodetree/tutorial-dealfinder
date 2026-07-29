"""ML & DL breadth (Part 21): gradient boosting, a price-drop forecaster, and a
real PyTorch training loop — all on the frozen snapshot's §4 features.

Part 3 motivates this: the from-scratch **linear** baseline in ``dealmodel.py`` is
deliberately weak on broad, heterogeneous electronics. Here we show what closes
the gap, and we report the TRUE numbers rather than the old narrow-tent course's
aspirational "~$80 → ~$35" (that figure was a single-category sandbox; on this
real 270-item / 11-category corpus the absolute MAE is much larger because a few
listings run into the thousands of dollars — a $13,599 RTX card, $2,299 laptops).
The honest story is a **relative** one: embeddings + boosting cut MAE by ~39% on
the full corpus, and by ~23% on the audio hero-cast subset. All values below are
computed against the committed snapshot and pinned in ``tests/test_models.py``.

Three pieces:

1. :func:`gbdt_vs_linear` — a scikit-learn ``GradientBoostingRegressor`` on the
   §4 hand features + PCA-compressed title embeddings, compared head-to-head with
   the linear baseline on the same deterministic split. Real MAE, both models.
2. :func:`forecast_price_drop` + :func:`synthetic_price_history` — a small, honest
   linear-trend forecaster. The snapshot has **no ``price_history``** (it is empty
   on all 270 rows — see ``load_snapshot``), so we forecast on a *deterministic
   synthetic* history and say so plainly. This is illustrative, not a claim about
   real time-series data we don't have.
3. :func:`train_torch_pricehead` — a minimal but REAL PyTorch MLP regressor
   trained with an actual autograd loop on the same features. torch installs
   cleanly in this venv (CPU), so this is a real, run-here training loop, not an
   anchored snippet. Seeded → deterministic MAE.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dealmodel import LinearModel, mae
from .features import feature_matrix
from .schema import Product
from .snapshot import load_products

# Deterministic split + model config. Pinned so quoted MAEs never drift.
_SPLIT_SEED = 0
_TEST_FRAC = 0.25
_PCA_COMPONENTS = 16
_GBDT_SEED = 0


def _aligned_embeddings(products: list[Product]) -> np.ndarray:
    """The cached 384-dim title embedding for each product, in product order."""
    from .embed import load_title_embeddings

    ids, vectors = load_title_embeddings()
    order = {i: k for k, i in enumerate(ids)}
    return np.asarray([vectors[order[p.id]] for p in products], dtype=float)


def _split(n: int, *, test_frac: float = _TEST_FRAC, seed: int = _SPLIT_SEED):
    """Deterministic index split (same seed → same split)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_test = int(round(n * test_frac))
    return idx[n_test:], idx[:n_test]


# ---------------------------------------------------------------------------
# 1. Gradient-boosted fair-price regressor vs. the linear baseline.
# ---------------------------------------------------------------------------
@dataclass
class ModelComparison:
    category: str          # "all" or a category name
    n_train: int
    n_test: int
    linear_mae: float      # the from-scratch baseline (dealmodel.py)
    gbdt_mae: float        # GradientBoostingRegressor on hand + embedding PCA
    improvement_pct: float  # (linear - gbdt) / linear * 100


def gbdt_vs_linear(
    category: str | None = None,
    *,
    with_embeddings: bool = True,
    pca_components: int = _PCA_COMPONENTS,
) -> ModelComparison:
    """Fit the linear baseline and a GBDT on the same split; report both MAEs.

    ``category=None`` uses the whole corpus; pass a category name (e.g. ``"audio"``)
    to compare on the hero-cast subset. With ``with_embeddings`` the GBDT also sees
    the title embedding compressed to ``pca_components`` PCA dims (the signal the
    3-dim hand vector can't carry). Deterministic — the split and both models are
    seeded.
    """
    from sklearn.decomposition import PCA
    from sklearn.ensemble import GradientBoostingRegressor

    products = load_products()
    if category is not None:
        products = [p for p in products if p.category == category]

    X_hand = feature_matrix(products)
    y = np.asarray([p.price for p in products], dtype=float)
    tr, te = _split(len(products))

    # Linear baseline: hand features only (that is the pinned baseline model).
    lin = LinearModel().fit(X_hand[tr], y[tr])
    linear_mae = mae(y[te], lin.predict(X_hand[te]))

    # GBDT: hand features, plus PCA-compressed embeddings when requested. PCA is
    # fit on TRAIN ONLY (no leakage into the test transform).
    if with_embeddings:
        emb = _aligned_embeddings(products)
        n_comp = min(pca_components, X_hand[tr].shape[0], emb.shape[1])
        pca = PCA(n_components=n_comp, random_state=_GBDT_SEED).fit(emb[tr])
        Xtr = np.hstack([X_hand[tr], pca.transform(emb[tr])])
        Xte = np.hstack([X_hand[te], pca.transform(emb[te])])
    else:
        Xtr, Xte = X_hand[tr], X_hand[te]

    gbdt = GradientBoostingRegressor(random_state=_GBDT_SEED).fit(Xtr, y[tr])
    gbdt_mae = mae(y[te], gbdt.predict(Xte))

    improvement = (linear_mae - gbdt_mae) / linear_mae * 100 if linear_mae else 0.0
    return ModelComparison(
        category=category or "all",
        n_train=len(tr), n_test=len(te),
        linear_mae=round(linear_mae, 2), gbdt_mae=round(gbdt_mae, 2),
        improvement_pct=round(improvement, 1),
    )


# ---------------------------------------------------------------------------
# 2. Price-drop forecaster (ILLUSTRATIVE — synthetic history, see docstring).
# ---------------------------------------------------------------------------
def synthetic_price_history(anchor_price: float, n: int = 12, *, seed: int = 42) -> np.ndarray:
    """A DETERMINISTIC synthetic weekly price history around an anchor price.

    The snapshot carries no real ``price_history``; this fabricates a plausible
    one — a mild downtrend from ~6% above the anchor toward it, with small seeded
    noise — so the forecaster has something to run on. It is illustrative ONLY.
    Same ``anchor_price``/``seed`` → identical series.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    start = anchor_price * 1.06
    slope = -anchor_price * 0.06 / (n - 1)
    noise = rng.normal(0.0, anchor_price * 0.01, n)
    return start + slope * t + noise


@dataclass
class Forecast:
    last_price: float
    forecast_next: float   # projected next-step price
    slope_per_step: float  # fitted linear trend (negative = falling)
    drop_pct: float        # (last - forecast) / last * 100; positive = expected drop
    will_drop: bool
    illustrative: bool = True  # ALWAYS true here — synthetic history, not real data


def forecast_price_drop(history: np.ndarray | list[float]) -> Forecast:
    """Fit a linear trend to a price history and project the next step.

    A deliberately small, honest heuristic (least-squares line, one-step
    projection) — not an ARIMA/Prophet pretence on data we don't have. Marks its
    output ``illustrative`` because the only histories available in this course
    are synthetic (see :func:`synthetic_price_history`). Deterministic in its
    input.
    """
    h = np.asarray(history, dtype=float)
    if h.size < 2:
        raise ValueError("need at least 2 price points to fit a trend")
    t = np.arange(h.size)
    slope, intercept = np.polyfit(t, h, 1)
    nxt = float(intercept + slope * h.size)
    last = float(h[-1])
    drop_pct = (last - nxt) / last * 100 if last else 0.0
    return Forecast(
        last_price=round(last, 2),
        forecast_next=round(nxt, 2),
        slope_per_step=round(float(slope), 3),
        drop_pct=round(drop_pct, 2),
        will_drop=nxt < last,
        illustrative=True,
    )


# ---------------------------------------------------------------------------
# 3. A minimal but REAL PyTorch training loop (tiny MLP regressor).
# ---------------------------------------------------------------------------
@dataclass
class TorchResult:
    n_train: int
    n_test: int
    mae: float          # test MAE in dollars
    final_loss: float   # final training MSE (standardized space)
    epochs: int
    real: bool = True   # torch runs here in the venv — this is a real loop


def train_torch_pricehead(
    *,
    epochs: int = 300,
    hidden: int = 16,
    lr: float = 0.05,
    seed: int = 0,
) -> TorchResult:
    """Train a tiny MLP price regressor with a real PyTorch autograd loop.

    Standardizes the §4 hand features and log-transforms the target for stability,
    then runs an actual ``loss.backward()`` / ``opt.step()`` loop. torch installs
    cleanly (CPU) in this venv, so this executes for real and is test-pinned;
    seeded for a deterministic MAE. (If torch were unavailable, the same loop
    lives in ``scripts/torch_pricehead.py`` for an environment that has it.)
    """
    import torch
    from torch import nn

    products = load_products()
    X = feature_matrix(products)
    y = np.asarray([p.price for p in products], dtype=float)
    tr, te = _split(len(products))

    # Standardize features and log1p the target — fit stats on TRAIN only.
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-8
    Xtr, Xte = (X[tr] - mu) / sd, (X[te] - mu) / sd
    ly = np.log1p(y[tr])
    ymu, ysd = ly.mean(), ly.std() + 1e-8
    ytr = (ly - ymu) / ysd

    torch.manual_seed(seed)
    Xt = torch.tensor(Xtr, dtype=torch.float32)
    yt = torch.tensor(ytr, dtype=torch.float32).view(-1, 1)
    net = nn.Sequential(nn.Linear(X.shape[1], hidden), nn.ReLU(), nn.Linear(hidden, 1))
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    loss = torch.tensor(float("nan"))
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(net(Xt), yt)
        loss.backward()
        opt.step()

    net.eval()
    with torch.no_grad():
        pz = net(torch.tensor(Xte, dtype=torch.float32)).numpy().ravel()
    preds = np.expm1(pz * ysd + ymu)  # invert the target transform → dollars

    return TorchResult(
        n_train=len(tr), n_test=len(te),
        mae=round(mae(y[te], preds), 2),
        final_loss=round(float(loss.item()), 5),
        epochs=epochs, real=True,
    )
