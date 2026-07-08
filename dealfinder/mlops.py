"""Closing the MLOps loop (Part 20): drift → retrain → eval gate → promote.

The pieces exist already; this part *wires them into a loop* and makes the
promotion decision explicit and auditable. One cycle:

1. **Drift check** (``ops.population_stability_index`` / ``ops.has_drifted``).
   Compare the live feature mix against the reference (snapshot) mix. PSI ≥ 0.2 =
   significant drift → a retrain is warranted. We drive it with a *deterministic*
   category-mix shift so the numbers reproduce: a mild 10% shift gives **PSI 0.043
   (no drift)**; a 30% shift gives **PSI 0.318 (drift — retrain)**.
2. **Retrain** the price model on the frozen snapshot (``dataset`` + ``models``) —
   deterministic, offline.
3. **Eval gate** (``evals``): the retrained candidate must clear the one
   course-wide gate, **precision@5 ≥ 0.80** on the golden set (spec §9.4).
4. **Champion / challenger promotion.** Promote the challenger **only if** it
   passes the gate **AND** beats the incumbent champion's precision@5. The
   two-signal ranker scores **precision@5 = 1.00** and is promoted over a
   median-only champion (0.40); a deliberately weak median-only challenger is
   **rejected** by the gate.

Everything is deterministic and offline against the committed snapshot. The whole
cycle returns a structured :class:`CycleDecision` trace so the decision is
auditable — the point of MLOps is that "we promoted model B" is *recorded and
reproducible*, not a shrug.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .evals import GATE_K, GATE_PRECISION, evaluate, median_only_ranker, two_signal_ranker
from .features import category_code
from .models import gbdt_vs_linear
from .ops import has_drifted, population_stability_index
from .snapshot import load_products

DRIFT_THRESHOLD = 0.2  # PSI rule of thumb (ops.has_drifted default)


# ---------------------------------------------------------------------------
# 1. Drift — a deterministic, reproducible feature-mix shift.
# ---------------------------------------------------------------------------
def reference_category_histogram(products=None) -> np.ndarray:
    """The reference feature distribution: category-code counts over the snapshot.

    Deterministic — this is the fixed baseline the live mix is compared against.
    """
    products = products if products is not None else load_products()
    codes = np.array([category_code(p.category) for p in products])
    hist, _ = np.histogram(codes, bins=11, range=(0, 11))
    return hist.astype(float)


def shift_distribution(ref: np.ndarray, frac: float) -> np.ndarray:
    """Deterministically move ``frac`` of the mass toward the high-code categories.

    Simulates a live traffic mix drifting toward pricier categories (computers,
    displays, misc). ``frac=0`` returns the reference unchanged; larger ``frac`` =
    more drift. Fully deterministic in ``(ref, frac)`` so the PSI reproduces.
    """
    h = ref.astype(float).copy()
    moved = h * frac
    h = h - moved
    h[-3:] += moved.sum() / 3.0
    return h


@dataclass
class DriftReport:
    psi: float
    threshold: float
    drifted: bool
    frac: float

    @property
    def action(self) -> str:
        return "retrain" if self.drifted else "hold"


def check_drift(frac: float, *, products=None) -> DriftReport:
    """PSI between the reference mix and a ``frac``-shifted live mix.

    ``frac=0.1`` → PSI ≈ 0.043 (no drift, hold); ``frac=0.3`` → PSI ≈ 0.318
    (drift, retrain). Both reproduce exactly (deterministic shift).
    """
    ref = reference_category_histogram(products)
    cur = shift_distribution(ref, frac)
    psi = round(population_stability_index(ref, cur), 4)
    return DriftReport(
        psi=psi,
        threshold=DRIFT_THRESHOLD,
        drifted=has_drifted(ref, cur, DRIFT_THRESHOLD),
        frac=frac,
    )


# ---------------------------------------------------------------------------
# 2. Retrain (deterministic, offline) — the price model on the snapshot.
# ---------------------------------------------------------------------------
@dataclass
class RetrainReport:
    linear_mae: float
    gbdt_mae: float
    improvement_pct: float
    n_train: int
    n_test: int


def retrain() -> RetrainReport:
    """Retrain the fair-price model on the frozen snapshot (deterministic).

    Reuses ``models.gbdt_vs_linear`` — the GBDT (hand + embeddings) is the model we
    ship, with the pinned $138.11 MAE vs the $227.89 linear baseline.
    """
    c = gbdt_vs_linear()
    return RetrainReport(
        linear_mae=c.linear_mae, gbdt_mae=c.gbdt_mae,
        improvement_pct=c.improvement_pct,
        n_train=c.n_train, n_test=c.n_test,
    )


# ---------------------------------------------------------------------------
# 3 + 4. Eval gate + champion/challenger promotion.
# ---------------------------------------------------------------------------
# The two rankers the loop can promote (the Part-3/19 A/B), named for the trace.
RANKERS = {
    "two_signal": two_signal_ranker,
    "median_only": median_only_ranker,
}


@dataclass
class GateReport:
    challenger: str
    precision_at_5: float
    gate: float
    passes_gate: bool


def eval_gate(challenger: str) -> GateReport:
    """Run the eval gate for a named challenger ranker (precision@5 ≥ 0.80).

    ``two_signal`` scores 1.00 (passes); ``median_only`` scores 0.40 (fails) — the
    too-good-to-be-true traps top its list (spec §9.4, Part 19).
    """
    ranker = RANKERS[challenger]
    res = evaluate(ranker)
    return GateReport(
        challenger=challenger,
        precision_at_5=res["precision_at_5"],
        gate=GATE_PRECISION,
        passes_gate=res["passes_gate"],
    )


@dataclass
class CycleDecision:
    """The full auditable trace of one MLOps cycle."""

    drift: DriftReport
    retrained: bool
    retrain_report: RetrainReport | None
    gate: GateReport | None
    champion: str
    champion_precision_at_5: float
    challenger: str
    promote: bool
    reason: str
    trace: list[str] = field(default_factory=list)


def _champion_precision(champion: str | None) -> float:
    """Champion's current precision@5 (a fresh champion starts at 0.0)."""
    if champion is None:
        return 0.0
    return evaluate(RANKERS[champion])["precision_at_5"]


def run_mlops_cycle(
    *,
    frac: float = 0.3,
    challenger: str = "two_signal",
    champion: str | None = "median_only",
) -> CycleDecision:
    """Run one drift → retrain → eval-gate → promote cycle, returning the trace.

    Defaults model the headline scenario: the live mix has drifted (``frac=0.3`` →
    PSI 0.318), so we retrain and evaluate the ``two_signal`` challenger, which
    clears the gate at precision@5 = 1.00 and is promoted over the ``median_only``
    champion (0.40). Deterministic and offline.

    Promotion rule (both conditions required):
      * the challenger PASSES the eval gate (precision@5 ≥ 0.80), AND
      * it BEATS the champion's precision@5.
    """
    trace: list[str] = []

    # 1. Drift.
    drift = check_drift(frac)
    trace.append(
        f"drift: PSI={drift.psi} vs threshold {drift.threshold} → "
        f"{'DRIFT, retrain' if drift.drifted else 'no drift, hold'}"
    )

    # If no drift, hold — no retrain, no promotion. The loop is a no-op by design.
    if not drift.drifted:
        champ_p = _champion_precision(champion)
        trace.append("no retrain (no drift); champion retained")
        return CycleDecision(
            drift=drift, retrained=False, retrain_report=None, gate=None,
            champion=champion or "(none)", champion_precision_at_5=champ_p,
            challenger=challenger, promote=False,
            reason="no drift detected — champion retained, nothing to promote",
            trace=trace,
        )

    # 2. Retrain.
    rr = retrain()
    trace.append(
        f"retrain: GBDT MAE ${rr.gbdt_mae} vs linear ${rr.linear_mae} "
        f"({rr.improvement_pct}% better) on {rr.n_train}/{rr.n_test} split"
    )

    # 3. Eval gate.
    gate = eval_gate(challenger)
    trace.append(
        f"gate: {challenger} precision@{GATE_K}={gate.precision_at_5} "
        f"vs {gate.gate} → {'PASS' if gate.passes_gate else 'FAIL'}"
    )

    # 4. Champion / challenger promotion (both conditions required).
    champ_p = _champion_precision(champion)
    beats_champion = gate.precision_at_5 > champ_p
    promote = gate.passes_gate and beats_champion
    if promote:
        reason = (
            f"promoted: {challenger} passed the gate "
            f"(p@5={gate.precision_at_5} ≥ {gate.gate}) and beat champion "
            f"{champion} ({champ_p})"
        )
    elif not gate.passes_gate:
        reason = (
            f"rejected: {challenger} failed the eval gate "
            f"(p@5={gate.precision_at_5} < {gate.gate})"
        )
    else:
        reason = (
            f"rejected: {challenger} passed the gate but did not beat champion "
            f"{champion} ({gate.precision_at_5} ≤ {champ_p})"
        )
    trace.append(reason)

    return CycleDecision(
        drift=drift, retrained=True, retrain_report=rr, gate=gate,
        champion=champion or "(none)", champion_precision_at_5=champ_p,
        challenger=challenger, promote=promote, reason=reason, trace=trace,
    )
