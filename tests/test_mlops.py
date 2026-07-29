"""Closing the MLOps loop (Part 24) — deterministic, offline against the snapshot.

Pins the real numbers of one drift → retrain → eval-gate → promote cycle:
a mild shift does NOT trip drift; a strong shift trips it (PSI ≥ 0.2); the
two-signal challenger clears the gate (precision@5 = 1.00) and is promoted; a
deliberately weak median-only challenger is rejected by the gate.
"""
import pytest

from dealfinder.mlops import (
    DRIFT_THRESHOLD,
    check_drift,
    eval_gate,
    run_mlops_cycle,
)


def test_mild_shift_does_not_trip_drift():
    d = check_drift(0.1)
    # REAL PSI ~0.043 — below the 0.2 threshold, so no retrain.
    assert d.psi == pytest.approx(0.0426, abs=0.005)
    assert d.drifted is False
    assert d.action == "hold"


def test_strong_shift_trips_drift():
    d = check_drift(0.3)
    # REAL PSI ~0.318 — crosses the 0.2 threshold → retrain.
    assert d.psi == pytest.approx(0.3182, abs=0.005)
    assert d.psi >= DRIFT_THRESHOLD
    assert d.drifted is True
    assert d.action == "retrain"


def test_two_signal_challenger_passes_gate_and_is_promoted():
    d = run_mlops_cycle(frac=0.3, challenger="two_signal", champion="median_only")
    assert d.drift.drifted is True
    assert d.retrained is True
    # Real retrain numbers reproduce (spec §9: GBDT $138.11 vs linear $227.89).
    assert d.retrain_report.gbdt_mae == pytest.approx(138.11, abs=2.0)
    # The gate: precision@5 == 1.00 (the two-signal ranker perfectly ranks deals).
    assert d.gate.precision_at_5 == pytest.approx(1.0)
    assert d.gate.passes_gate is True
    # Beats the median-only champion (0.40) → promoted.
    assert d.champion_precision_at_5 == pytest.approx(0.4)
    assert d.promote is True
    assert "promoted" in d.reason


def test_weak_challenger_is_rejected_by_the_gate():
    d = run_mlops_cycle(frac=0.3, challenger="median_only", champion="two_signal")
    # median-only tops its list with the traps → precision@5 = 0.40, fails gate.
    assert d.gate.precision_at_5 == pytest.approx(0.4)
    assert d.gate.passes_gate is False
    assert d.promote is False
    assert "failed the eval gate" in d.reason


def test_passing_challenger_that_does_not_beat_champion_is_not_promoted():
    # Same ranker as champion and challenger: passes the gate but ties (not >), so
    # promotion requires BEATING the champion, not merely matching it.
    d = run_mlops_cycle(frac=0.3, challenger="two_signal", champion="two_signal")
    assert d.gate.passes_gate is True
    assert d.promote is False
    assert d.reason.startswith("rejected: two_signal passed the gate but did not beat")


def test_no_drift_holds_without_retrain_or_promotion():
    d = run_mlops_cycle(frac=0.1)
    assert d.drift.drifted is False
    assert d.retrained is False
    assert d.retrain_report is None
    assert d.gate is None
    assert d.promote is False


def test_eval_gate_standalone_matches_the_pinned_ab():
    assert eval_gate("two_signal").precision_at_5 == pytest.approx(1.0)
    assert eval_gate("median_only").precision_at_5 == pytest.approx(0.4)
