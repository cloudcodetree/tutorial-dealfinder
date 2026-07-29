"""Inference optimization (Part 27) — offline. Pins the MEASURED pieces (semantic
cache hit rate + the cosine threshold that governs it, and the router escalation
logic) and asserts the illustrative/anchored pieces are honestly flagged.
"""
import pytest

from dealfinder.inference import (
    CascadeRouter,
    measure_cache_hit_rate,
    model_batching_throughput,
    quantization_reference,
    run_inference_report,
    vllm_reference,
)


# --- 1. Semantic cache hit rate (MEASURED) ---------------------------------
def test_cache_hit_rate_at_095_exact_repeats_only():
    r = measure_cache_hit_rate(0.95)
    assert r.measured is True
    assert r.n_queries == 14
    # Only the exact repeats hit at 0.95 → 6/14 = 0.429.
    assert r.hits == 6
    assert r.hit_rate == pytest.approx(0.429, abs=0.001)


def test_lowering_threshold_to_090_admits_the_real_near_duplicate():
    r = measure_cache_hit_rate(0.90)
    # The Sony WH-1000XM5 pair has REAL cosine 0.9498 → now above a 0.90 threshold,
    # so it becomes a 7th hit: 7/14 = 0.500. The threshold IS the knob.
    assert r.near_duplicate_cosine == pytest.approx(0.9498, abs=0.001)
    assert r.hits == 7
    assert r.hit_rate == pytest.approx(0.5, abs=0.001)
    # 0.90 <= 0.9498 (admits it); 0.95 > 0.9498 (excludes it) — the governing fact.
    assert 0.90 <= r.near_duplicate_cosine < 0.95


# --- 2. Router / cascade escalation (MEASURED logic, injected transport) ----
def test_router_serves_from_cheapest_tier_when_it_answers():
    r = CascadeRouter(lambda m, p: f"ok:{m}", tiers=["cheap", "free"]).route("q")
    assert r.model == "cheap"
    assert r.attempts == ["cheap"]
    assert r.escalated is False


def test_router_escalates_when_cheap_tier_fails():
    def call(model, prompt):
        if model == "cheap":
            raise RuntimeError("429 throttled")
        return f"ok:{model}"

    r = CascadeRouter(call, tiers=["cheap", "free"]).route("q")
    assert r.model == "free"
    assert r.attempts == ["cheap", "free"]
    assert r.escalated is True


def test_router_escalates_on_low_confidence():
    # cheap answers but with low confidence → escalate to free.
    def conf(answer: str) -> float:
        return 0.9 if "free" in answer else 0.2

    r = CascadeRouter(
        lambda m, p: f"ans:{m}", tiers=["cheap", "free"],
        confidence=conf, min_confidence=0.5,
    ).route("q")
    assert r.model == "free"
    assert r.escalated is True


def test_router_raises_when_all_tiers_exhausted():
    def call(model, prompt):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="all tiers exhausted"):
        CascadeRouter(call, tiers=["cheap", "free"]).route("q")


# --- 3 + 4. Illustrative / anchored pieces are honestly flagged -------------
def test_batching_is_marked_illustrative_and_amortizes_overhead():
    b = model_batching_throughput()
    assert b.illustrative is True         # a MODEL, not a benchmark
    assert b.batched_seconds < b.per_item_seconds
    assert b.speedup > 1.0


def test_quant_and_vllm_are_anchored_never_measured():
    for a in (quantization_reference(), vllm_reference()):
        assert a.illustrative is True     # NEVER presented as measured
        assert a.runnable_script.endswith(".py")
        assert "illustrative" in a.note.lower()


def test_full_report_has_measured_cache_and_anchored_gpu_refs():
    rep = run_inference_report()
    assert rep.cache_at_095.measured and rep.cache_at_090.measured
    assert rep.cache_at_090.hit_rate > rep.cache_at_095.hit_rate
    assert all(a.illustrative for a in rep.anchored)
