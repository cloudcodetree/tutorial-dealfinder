"""Observability & FinOps: know what your AI system costs and when it goes stale.

CostTracker attributes spend per model (the heart of an AI cost dashboard);
budget_status drives alerts; and a population-stability index flags input drift
so you can trigger a retrain before quality silently rots.
"""
from __future__ import annotations

import numpy as np

# $ per 1M tokens (input, output) — illustrative public-ish rates
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}


class CostTracker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, model: str, in_tok: int, out_tok: int) -> float:
        p_in, p_out = PRICES[model]
        cost = (in_tok * p_in + out_tok * p_out) / 1e6
        self.calls.append({"model": model, "cost": cost, "in": in_tok, "out": out_tok})
        return cost

    def total(self) -> float:
        return sum(c["cost"] for c in self.calls)

    def by_model(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for c in self.calls:
            out[c["model"]] = out.get(c["model"], 0.0) + c["cost"]
        return out


def budget_status(spent: float, budget: float) -> str:
    frac = spent / budget
    return "ok" if frac < 0.8 else ("warn" if frac < 1.0 else "over")


def population_stability_index(ref, cur) -> float:
    """PSI between two distributions. Rule of thumb: >0.2 = significant drift."""
    ref = np.asarray(ref, dtype=float)
    cur = np.asarray(cur, dtype=float)
    ref = np.clip(ref / ref.sum(), 1e-6, None)
    cur = np.clip(cur / cur.sum(), 1e-6, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def has_drifted(ref, cur, threshold: float = 0.2) -> bool:
    return population_stability_index(ref, cur) >= threshold
