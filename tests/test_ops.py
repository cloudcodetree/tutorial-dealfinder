import math

from dealfinder.ops import CostTracker, budget_status, has_drifted, population_stability_index


def test_cost_tracker_attributes_by_model():
    t = CostTracker()
    t.record("gpt-4o-mini", in_tok=1000, out_tok=500)   # (1000*.15 + 500*.60)/1e6
    t.record("gpt-4o", in_tok=1000, out_tok=0)
    assert math.isclose(t.total(), 0.00045 + 0.0025, rel_tol=1e-9)
    assert set(t.by_model()) == {"gpt-4o-mini", "gpt-4o"}


def test_budget_status_thresholds():
    assert budget_status(0.5, 1.0) == "ok"
    assert budget_status(0.85, 1.0) == "warn"
    assert budget_status(1.2, 1.0) == "over"


def test_drift_detection():
    ref = [50, 30, 20]
    assert population_stability_index(ref, ref) == 0.0      # identical → no drift
    assert not has_drifted(ref, [49, 31, 20])               # tiny shift
    assert has_drifted(ref, [10, 30, 60])                   # big shift → drift
