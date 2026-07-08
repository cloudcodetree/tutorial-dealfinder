"""Experiment tracking (Part 18) — offline, local SQLite MLflow store.

Pins the model-selection wiring: on the shared fair-price feature contract the
GBDT run wins by MAE ($138.11), the metrics are logged, and the winner is
registered in a local model registry. Skips cleanly if MLflow is not installed
(mirrors ``tests/test_pgstore.py`` skipping without ``DATABASE_URL``) — but MLflow
installs cleanly in this venv, so it runs for real.
"""
import pytest

from dealfinder.tracking import mlflow_available, run_tracking

pytestmark = pytest.mark.skipif(not mlflow_available(), reason="mlflow not installed")


def _by_name(res):
    return {r.name: r for r in res.runs}


def test_gbdt_is_the_selected_winner_by_mae():
    res = run_tracking()
    # GBDT wins the same-features selection (spec/task: winner == GBDT).
    assert res.winner == "gbdt"
    assert res.winner_mae == pytest.approx(138.11, abs=2.0)
    assert res.registered_model == "dealfinder-fair-price"
    assert res.tracking_uri.startswith("sqlite:///")


def test_selectable_runs_share_the_fair_price_contract_and_gbdt_beats_them():
    res = run_tracking()
    runs = _by_name(res)
    # All selectable runs on the identical hand+emb matrix — a fair comparison.
    for name in ("linear", "gbdt"):
        assert runs[name].contract == "fair-price"
        assert runs[name].selectable is True
    # REAL MAEs on the contract: linear ~$257.85, gbdt ~$138.11 (the winner).
    assert runs["linear"].mae == pytest.approx(257.85, abs=1.5)
    assert runs["gbdt"].mae == pytest.approx(138.11, abs=2.0)
    assert runs["gbdt"].mae < runs["linear"].mae
    # R² is logged for both tabular runs; GBDT explains far more variance.
    assert runs["gbdt"].r2 == pytest.approx(0.727, abs=0.02)
    assert runs["linear"].r2 < runs["gbdt"].r2


def test_documented_baselines_reproduce_and_are_not_selectable():
    res = run_tracking()
    runs = _by_name(res)
    # The prose numbers must reproduce verbatim: linear $227.89, torch $117.11.
    assert runs["linear_baseline"].mae == pytest.approx(227.89, abs=1.0)
    assert runs["linear_baseline"].contract == "documented-baseline"
    assert runs["linear_baseline"].selectable is False
    if res.torch_available:
        # torch on hand-only is LOWER ($117.11) — but on a DIFFERENT feature set,
        # so it is honestly excluded from the same-features winner selection.
        assert runs["torch_baseline"].mae == pytest.approx(117.11, abs=3.0)
        assert runs["torch_baseline"].selectable is False
        assert runs["torch_baseline"].mae < res.winner_mae


def test_comparison_table_marks_the_winner():
    res = run_tracking()
    table = res.comparison_table()
    assert "gbdt" in table and "*" in table
    # every logged run appears in the table
    for r in res.runs:
        assert r.name in table
