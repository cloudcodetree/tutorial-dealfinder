"""A linear price model, trained from scratch with the normal equation.

No scikit-learn: the point is to see the math. Given a feature matrix X and
target prices y, we solve for the weights theta that minimise squared error:

    theta = (Xb^T Xb)^-1 Xb^T y          (the "normal equation")

where Xb is X with a leading column of 1s so theta[0] is the intercept. We use
np.linalg.pinv (the pseudo-inverse) so it stays stable even if columns are
collinear — mathematically identical to the inverse when X^T X is invertible.
"""
from __future__ import annotations

import numpy as np


def _with_bias(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    return np.hstack([np.ones((X.shape[0], 1)), X])


class LinearModel:
    """Ordinary least squares via the normal equation. coef_[0] is the intercept."""

    def __init__(self) -> None:
        self.coef_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LinearModel":
        Xb = _with_bias(X)
        y = np.asarray(y, dtype=float)
        self.coef_ = np.linalg.pinv(Xb.T @ Xb) @ Xb.T @ y
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise ValueError("model is not fitted — call fit() first")
        return _with_bias(X) @ self.coef_


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean absolute error — average dollars off, in the unit you care about."""
    return float(np.mean(np.abs(np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float))))


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination — fraction of price variance the model explains."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 1.0 - ss_res / ss_tot


def train_test_split(n: int, test_frac: float = 0.25, seed: int = 0):
    """Deterministic index split — same seed, same split (so results reproduce)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_test = max(1, int(round(n * test_frac)))
    return idx[n_test:], idx[:n_test]
