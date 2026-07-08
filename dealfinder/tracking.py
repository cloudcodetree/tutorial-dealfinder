"""Experiment tracking & a model registry (Part 18): MLflow over the three real
price models, against the frozen snapshot.

Part 17 built three fair-price regressors — a from-scratch **linear** baseline
(``dealmodel.py``), a **gradient-boosted** model (``models.gbdt_vs_linear``), and a
real **PyTorch MLP** (``models.train_torch_pricehead``). Training them is only half
the job; the other half is *remembering what you tried*. This module wraps each
training run with MLflow logging (params + the metrics MAE and R²) to a LOCAL
file-store — no tracking server, no network — then registers and selects the best
run **by MAE**.

Honesty about the comparison (this feeds a tutorial that must not lie):

* You can only rank models fairly on the **same feature representation**. The one
  the course's fair-price/dealscore path actually uses is the §4 vector *plus* the
  PCA-compressed title embedding (``models.gbdt_vs_linear`` fits GBDT on exactly
  that). So the head-to-head **selection** is run on that shared "fair-price
  contract," where the REAL MAEs are:

      linear (hand+emb)  MAE $257.85   R² 0.010
      gbdt   (hand+emb)  MAE $138.11   R² 0.727   ← winner by MAE
      torch  (hand+emb)  MAE $149.21   (real autograd loop, seeded)

  GBDT genuinely wins. We do NOT cherry-pick features to manufacture a winner:
  every model sees the identical matrix.

* We ALSO log the two **documented Part-17 baselines** as their own runs so the
  numbers the prose quotes reproduce here verbatim: the hand-only linear baseline
  **$227.89** and the GBDT-with-embeddings **$138.11** (``models.gbdt_vs_linear()``),
  and the hand-only torch MLP **$117.11** (``models.train_torch_pricehead()``).
  These are tagged ``contract="documented-baseline"`` and excluded from the
  same-features selection — a lower MAE on a *different* feature set is not a fair
  win, and saying so is the lesson.

Everything is deterministic and offline. If MLflow is not importable the public
helpers raise a clear error and ``tests/test_tracking.py`` skips (mirroring how
``tests/test_pgstore.py`` skips without ``DATABASE_URL``) — but MLflow installs
cleanly in this venv, so it runs for real.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .dealmodel import LinearModel, mae, r2
from .features import feature_matrix
from .models import _split, gbdt_vs_linear, train_torch_pricehead
from .snapshot import load_products

# Deterministic config — must match models.py so the logged numbers reproduce.
_PCA_COMPONENTS = 16
_SEED = 0
_EXPERIMENT = "dealfinder-price-models"


def mlflow_available() -> bool:
    """True when MLflow can be imported (kept optional; heavy)."""
    try:
        import mlflow  # noqa: F401
    except Exception:
        return False
    return True


def _require_mlflow():
    try:
        import mlflow
    except Exception as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "mlflow is not installed; `pip install .[mlflow]` to enable experiment "
            "tracking (Part 18)."
        ) from e
    return mlflow


@contextmanager
def local_tracking(uri: str | None = None):
    """Point MLflow at a LOCAL store (a temp SQLite file by default) — no server.

    Yields the active ``mlflow`` module with ``tracking_uri`` set to a local
    ``sqlite:///`` URI under a temp dir. Everything MLflow writes (runs, params,
    metrics, the model registry) lands in that one file; nothing touches the
    network and no tracking server is launched. Restores the previous URI on exit.

    (MLflow 3 put the bare filesystem ``./mlruns`` backend into maintenance mode
    and made the registry require a database backend, so we use a local SQLite DB —
    still a single local file, still fully offline.)
    """
    mlflow = _require_mlflow()
    prev = mlflow.get_tracking_uri()
    tmp: tempfile.TemporaryDirectory | None = None
    if uri is None:
        tmp = tempfile.TemporaryDirectory(prefix="dealfinder-mlruns-")
        uri = f"sqlite:///{Path(tmp.name) / 'mlflow.db'}"
    try:
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(_EXPERIMENT)
        yield mlflow
    finally:
        mlflow.set_tracking_uri(prev)
        if tmp is not None:
            tmp.cleanup()


# ---------------------------------------------------------------------------
# The shared "fair-price contract" matrix (hand §4 features + PCA embeddings).
# This is the representation used for the fair, same-features model selection.
# ---------------------------------------------------------------------------
def _contract_matrix() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(Xtr, Xte, ytr, yte)`` on the fair-price feature contract.

    PCA is fit on TRAIN ONLY (no leakage), exactly as ``models.gbdt_vs_linear``
    does, so the GBDT MAE here matches the pinned $138.11.
    """
    from sklearn.decomposition import PCA

    from .embed import load_title_embeddings

    products = load_products()
    Xh = feature_matrix(products)
    y = np.asarray([p.price for p in products], dtype=float)
    tr, te = _split(len(products))

    ids, vectors = load_title_embeddings()
    order = {i: k for k, i in enumerate(ids)}
    emb = np.asarray([vectors[order[p.id]] for p in products], dtype=float)
    n_comp = min(_PCA_COMPONENTS, Xh[tr].shape[0], emb.shape[1])
    pca = PCA(n_components=n_comp, random_state=_SEED).fit(emb[tr])
    Xtr = np.hstack([Xh[tr], pca.transform(emb[tr])])
    Xte = np.hstack([Xh[te], pca.transform(emb[te])])
    return Xtr, Xte, y[tr], y[te]


def _torch_on_contract(Xtr, Xte, ytr, yte, *, epochs=300, hidden=16, lr=0.05, seed=_SEED) -> float:
    """A real seeded PyTorch MLP MAE on the fair-price contract matrix.

    Same loop as ``models.train_torch_pricehead`` but on the shared matrix so the
    three models are compared on identical features. Deterministic.
    """
    import torch
    from torch import nn

    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-8
    Xtr_, Xte_ = (Xtr - mu) / sd, (Xte - mu) / sd
    ly = np.log1p(ytr)
    ymu, ysd = ly.mean(), ly.std() + 1e-8
    ytr_ = (ly - ymu) / ysd

    torch.manual_seed(seed)
    Xt = torch.tensor(Xtr_, dtype=torch.float32)
    yt = torch.tensor(ytr_, dtype=torch.float32).view(-1, 1)
    net = nn.Sequential(nn.Linear(Xtr.shape[1], hidden), nn.ReLU(), nn.Linear(hidden, 1))
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(net(Xt), yt)
        loss.backward()
        opt.step()
    net.eval()
    with torch.no_grad():
        pz = net(torch.tensor(Xte_, dtype=torch.float32)).numpy().ravel()
    preds = np.expm1(pz * ysd + ymu)
    return round(mae(yte, preds), 2)


# ---------------------------------------------------------------------------
# Run records + the tracking loop.
# ---------------------------------------------------------------------------
@dataclass
class RunRecord:
    name: str            # model name
    contract: str        # "fair-price" (same-features, selectable) | "documented-baseline"
    mae: float
    r2: float | None
    params: dict = field(default_factory=dict)
    selectable: bool = True  # only same-features runs compete for the registry winner


@dataclass
class TrackingResult:
    experiment: str
    tracking_uri: str
    runs: list[RunRecord]
    winner: str          # model name selected by lowest MAE among selectable runs
    winner_mae: float
    registered_model: str
    torch_available: bool

    def comparison_table(self) -> str:
        """A plain-text comparison table (real numbers only)."""
        rows = ["model                metric  MAE ($)     R²     contract"]
        for r in self.runs:
            star = " *" if r.name == self.winner else "  "
            r2s = f"{r.r2:6.3f}" if r.r2 is not None else "   n/a"
            rows.append(
                f"{r.name:<18}{star} {r.mae:9.2f}  {r2s}   {r.contract}"
            )
        return "\n".join(rows)


def run_tracking(tracking_uri: str | None = None) -> TrackingResult:
    """Train the three price models, log each to a local MLflow store, select best.

    Logs (per run) the params and the metrics MAE + R² for:

    * the **selectable** same-features runs on the fair-price contract:
      ``linear`` ($257.85), ``gbdt`` ($138.11), and — when torch is present —
      ``torch`` ($149.21). The registry winner is the lowest-MAE of these.
    * the **documented baselines** (not selectable): ``linear_baseline`` ($227.89,
      hand-only) and ``torch_baseline`` ($117.11, hand-only), so the prose numbers
      reproduce verbatim here.

    Registers the winner in the local model registry as ``dealfinder-fair-price``.
    Returns a :class:`TrackingResult` with the full comparison. Deterministic.
    """
    torch_ok = _torch_installed()
    Xtr, Xte, ytr, yte = _contract_matrix()

    # --- selectable runs, all on the identical fair-price contract matrix ---
    lin = LinearModel().fit(Xtr, ytr)
    lin_pred = lin.predict(Xte)
    runs: list[RunRecord] = [
        RunRecord(
            "linear", "fair-price",
            round(mae(yte, lin_pred), 2), round(r2(yte, lin_pred), 3),
            params={"model": "LinearModel", "features": "hand+emb16", "solver": "normal-eq"},
        ),
    ]

    from sklearn.decomposition import PCA  # noqa: F401  (ensures sklearn is present)
    from sklearn.ensemble import GradientBoostingRegressor

    gbdt = GradientBoostingRegressor(random_state=_SEED).fit(Xtr, ytr)
    gbdt_pred = gbdt.predict(Xte)
    runs.append(
        RunRecord(
            "gbdt", "fair-price",
            round(mae(yte, gbdt_pred), 2), round(r2(yte, gbdt_pred), 3),
            params={"model": "GradientBoostingRegressor", "features": "hand+emb16",
                    "random_state": _SEED},
        )
    )

    if torch_ok:
        t_mae = _torch_on_contract(Xtr, Xte, ytr, yte)
        runs.append(
            RunRecord(
                "torch", "fair-price", t_mae, None,
                params={"model": "MLP", "features": "hand+emb16", "epochs": 300,
                        "hidden": 16, "lr": 0.05, "seed": _SEED},
            )
        )

    # --- documented Part-17 baselines (hand-only) — logged, not selectable ---
    doc = gbdt_vs_linear()  # linear $227.89 (hand), gbdt $138.11 (hand+emb)
    runs.append(
        RunRecord(
            "linear_baseline", "documented-baseline", doc.linear_mae, None,
            params={"model": "LinearModel", "features": "hand-only", "source": "Part 17"},
            selectable=False,
        )
    )
    if torch_ok:
        tb = train_torch_pricehead()  # $117.11 hand-only
        runs.append(
            RunRecord(
                "torch_baseline", "documented-baseline", tb.mae, None,
                params={"model": "MLP", "features": "hand-only", "epochs": tb.epochs},
                selectable=False,
            )
        )

    # --- select the winner over the SAME-features runs only, by MAE ---
    selectable = [r for r in runs if r.selectable]
    winner = min(selectable, key=lambda r: r.mae)

    registered = "dealfinder-fair-price"
    uri_used = tracking_uri or ""
    with local_tracking(tracking_uri) as mlflow:
        uri_used = mlflow.get_tracking_uri()
        winner_run_id = None
        for r in runs:
            with mlflow.start_run(run_name=r.name) as run:
                mlflow.log_params(r.params)
                mlflow.set_tag("contract", r.contract)
                mlflow.set_tag("selectable", str(r.selectable))
                mlflow.log_metric("mae", r.mae)
                if r.r2 is not None:
                    mlflow.log_metric("r2", r.r2)
                if r.name == winner.name:
                    winner_run_id = run.info.run_id
        # Register the winning run in the local model registry.
        try:
            mlflow.register_model(f"runs:/{winner_run_id}/model", registered)
        except Exception:
            # No artifact was logged (we log metrics, not the estimator), so create
            # the registry entry directly — the point is the *selection*, recorded.
            client = mlflow.tracking.MlflowClient()
            try:
                client.create_registered_model(registered)
            except Exception:
                pass
            client.set_registered_model_tag(registered, "winner_run_id", winner_run_id or "")
            client.set_registered_model_tag(registered, "winner", winner.name)
            client.set_registered_model_tag(registered, "winner_mae", str(winner.mae))

    return TrackingResult(
        experiment=_EXPERIMENT,
        tracking_uri=uri_used,
        runs=runs,
        winner=winner.name,
        winner_mae=winner.mae,
        registered_model=registered,
        torch_available=torch_ok,
    )


def _torch_installed() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:
        return False
    return True
