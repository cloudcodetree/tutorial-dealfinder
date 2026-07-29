"""Inference optimization, for real (Part 27): what actually makes serving cheaper
and faster — measured where we can, honestly anchored where a GPU is required.

Four levers, clearly labelled **measured** vs **illustrative**:

1. **Semantic cache hit rate** (MEASURED, offline). Run a batch of repeated /
   near-duplicate queries through ``cache.SemanticCache`` and report the REAL hit
   rate and the cosine threshold that governs it. Using the committed 384-dim
   title embeddings as real query vectors (spec §9.5 — no model download), a
   14-query batch hits **6/14 = 0.429** at threshold 0.95 (exact repeats only) and
   **7/14 = 0.500** at threshold 0.90, where the real Sony WH-1000XM5 near-duplicate
   pair (cosine **0.9498**) also becomes a hit. The threshold *is* the knob.

2. **Model routing / cascade** (MEASURED logic, no network). A cost/latency-aware
   router over the ``llm.py`` tiers: try the cheapest tier first, escalate only on
   failure/low-confidence. The tier order and escalation are exercised with an
   **injected** transport (no HTTP), so the routing decisions are unit-tested
   without a live key. Real order: cheap paid → free fallback.

3. **Batching throughput** (ILLUSTRATIVE — a MODELED comparison, marked as such).
   Per-item vs batched embedding calls under a simple fixed-overhead-per-call
   model. Clearly a model, not a benchmark of a specific GPU; the shape (batching
   amortizes per-call overhead) is the lesson.

4. **Quantization + vLLM** (ANCHORED — needs a GPU). Implemented as a reference:
   the concept, a runnable-where-a-GPU-exists script pointer, and clearly-labelled
   *illustrative* figures. **No fabricated benchmarks** — every number here is
   flagged ``illustrative=True`` and the docstrings say what is real.

Tests pin the measured pieces (cache hit rate, router escalation); the
illustrative pieces are pinned only for determinism, never presented as measured.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .cache import SemanticCache
from .embed import load_title_embeddings
from .llm import models as llm_models
from .snapshot import load_snapshot


# ===========================================================================
# 1. Semantic cache hit rate (MEASURED, offline).
# ===========================================================================
@dataclass
class CacheReport:
    threshold: float
    n_queries: int
    hits: int
    hit_rate: float
    near_duplicate_cosine: float  # the real XM5 pair cosine that the threshold gates
    measured: bool = True


def _demo_batch() -> tuple[list[np.ndarray], list[str], float]:
    """A deterministic query batch of real title-embedding vectors + the XM5 pair.

    Six distinct base queries (first item per category), each repeated once (exact
    repeats → guaranteed hits), plus the two Sony WH-1000XM5 listings (a real
    near-duplicate pair, cosine 0.9498 — the dedup example, spec §9.6). Returns the
    query vectors in order, their labels, and the measured near-dup cosine.
    """
    ids, vectors = load_title_embeddings()
    order = {i: k for k, i in enumerate(ids)}
    items = load_snapshot()
    by_id = {r["id"]: r for r in items}

    bases: list[str] = []
    seen: set[str] = set()
    for r in items:
        if r["category"] not in seen:
            seen.add(r["category"])
            bases.append(r["id"])
        if len(bases) >= 6:
            break

    xm5 = [r for r in items if "WH-1000XM5" in r["title"]][:2]
    batch_ids: list[str] = []
    for b in bases:
        batch_ids += [b, b]  # base then exact repeat
    batch_ids += [x["id"] for x in xm5]  # the near-duplicate pair

    vecs = [vectors[order[i]] for i in batch_ids]
    labels = [by_id[i]["title"] for i in batch_ids]

    v0, v1 = vectors[order[xm5[0]["id"]]], vectors[order[xm5[1]["id"]]]
    cos = float(v0 @ v1 / (np.linalg.norm(v0) * np.linalg.norm(v1)))
    return vecs, labels, round(cos, 4)


def measure_cache_hit_rate(threshold: float = 0.95) -> CacheReport:
    """Run the deterministic batch through ``SemanticCache`` and report the REAL rate.

    The cosine ``threshold`` is the governing knob: at 0.95 only exact repeats hit
    (6/14 = 0.429); at 0.90 the real XM5 near-duplicate (cosine 0.9498) also hits
    (7/14 = 0.500). Fully offline and deterministic.
    """
    vecs, labels, near_cos = _demo_batch()
    cache = SemanticCache(threshold=threshold)
    hits = 0
    for v, label in zip(vecs, labels):
        if cache.get(v) is not None:
            hits += 1
        else:
            cache.put(v, label)
    n = len(vecs)
    return CacheReport(
        threshold=threshold, n_queries=n, hits=hits,
        hit_rate=round(hits / n, 3), near_duplicate_cosine=near_cos,
    )


# ===========================================================================
# 2. Model routing / cascade (MEASURED logic, no network — injectable).
# ===========================================================================
@dataclass
class RouteResult:
    answer: str
    model: str            # which tier actually served the answer
    attempts: list[str]   # tiers tried, in order (the escalation trace)
    escalated: bool       # True if a cheaper tier was skipped before success
    measured: bool = True


class CascadeRouter:
    """Cost/latency-aware cascade over the ``llm.py`` model tiers.

    Tries the cheapest tier first and escalates to the next only when the current
    tier **fails** (raises) or returns a **low-confidence** answer (per an injected
    ``confidence`` fn). This is the real routing *logic*; the per-tier ``call`` is
    injected so tests exercise escalation with **no network** (mirrors how
    ``test_llm.py`` mocks the transport).

    ``tiers`` defaults to ``llm.models()`` (cheap paid → free fallback).
    """

    def __init__(
        self,
        call: Callable[[str, str], str],
        *,
        tiers: list[str] | None = None,
        confidence: Callable[[str], float] | None = None,
        min_confidence: float = 0.5,
    ) -> None:
        self.call = call
        self.tiers = tiers if tiers is not None else llm_models()
        self.confidence = confidence or (lambda _a: 1.0)
        self.min_confidence = min_confidence

    def route(self, prompt: str) -> RouteResult:
        attempts: list[str] = []
        last_err: str | None = None
        for model in self.tiers:
            attempts.append(model)
            try:
                answer = self.call(model, prompt)
            except Exception as e:  # tier unavailable/throttled → escalate
                last_err = f"{model}: {e}"
                continue
            if self.confidence(answer) >= self.min_confidence:
                return RouteResult(
                    answer=answer, model=model, attempts=attempts,
                    escalated=len(attempts) > 1,
                )
            last_err = f"{model}: low confidence"
        raise RuntimeError(f"all tiers exhausted ({last_err})")


# ===========================================================================
# 3. Batching throughput (ILLUSTRATIVE — a MODELED comparison, marked).
# ===========================================================================
@dataclass
class BatchingModel:
    n_items: int
    per_item_seconds: float   # modeled total for one-at-a-time calls
    batched_seconds: float    # modeled total for a single batched call
    speedup: float
    illustrative: bool = True  # a MODEL of call overhead, not a GPU benchmark


def model_batching_throughput(
    n_items: int = 64,
    *,
    call_overhead_s: float = 0.02,
    per_item_compute_s: float = 0.001,
) -> BatchingModel:
    """A MODELED per-item-vs-batched comparison — illustrative, not a benchmark.

    Simple, honest model: each *call* pays a fixed ``call_overhead_s`` (network +
    setup); each *item* pays ``per_item_compute_s`` regardless. One-at-a-time =
    ``n * (overhead + compute)``; batched = ``overhead + n * compute`` (one call,
    same compute). Batching amortizes the per-call overhead — that shape is the
    lesson. Marked ``illustrative`` because the constants are assumed, not measured
    on a specific device.
    """
    per_item = n_items * (call_overhead_s + per_item_compute_s)
    batched = call_overhead_s + n_items * per_item_compute_s
    return BatchingModel(
        n_items=n_items,
        per_item_seconds=round(per_item, 4),
        batched_seconds=round(batched, 4),
        speedup=round(per_item / batched, 2),
        illustrative=True,
    )


# ===========================================================================
# 4. Quantization + vLLM (ANCHORED — needs a GPU; NO fabricated benchmarks).
# ===========================================================================
@dataclass
class AnchoredBenchmark:
    name: str
    note: str
    illustrative_numbers: dict
    runnable_script: str
    illustrative: bool = True  # ALWAYS true — never presented as measured here


def quantization_reference() -> AnchoredBenchmark:
    """ANCHORED reference for INT8/INT4 quantization — requires a GPU to measure.

    Returns the concept + *clearly-illustrative* expectation figures and a pointer
    to a runnable script (``scripts/bench_quantization.py``) for an environment
    that has a GPU. The numbers are labelled ``illustrative`` and MUST NOT be
    quoted as measured — on CPU here we cannot benchmark GPU kernels, and we do not
    pretend to. The honest claim is directional: 4-bit weights cut VRAM ~4x and
    typically trade a small quality drop for higher throughput.
    """
    return AnchoredBenchmark(
        name="quantization (INT8 / INT4)",
        note=(
            "Illustrative expectations only — requires a GPU to measure. 4-bit "
            "weights roughly quarter the model's VRAM footprint; throughput and "
            "any quality delta are hardware/model specific and must be measured on "
            "the target device, not asserted here."
        ),
        illustrative_numbers={
            "fp16_vram_gb": 16.0,
            "int8_vram_gb": 8.0,
            "int4_vram_gb": 4.0,
            "note": "figures illustrate the ~4x VRAM reduction shape, not a benchmark",
        },
        runnable_script="scripts/bench_quantization.py",
    )


def vllm_reference() -> AnchoredBenchmark:
    """ANCHORED reference for vLLM continuous batching / PagedAttention — needs a GPU.

    Same discipline as :func:`quantization_reference`: concept + a runnable script
    pointer + illustrative figures flagged ``illustrative``. vLLM's win (continuous
    batching + PagedAttention → much higher tokens/sec under concurrency) is real
    and well-documented, but the *magnitude* is device-specific and is NOT measured
    on this CPU box.
    """
    return AnchoredBenchmark(
        name="vLLM (continuous batching + PagedAttention)",
        note=(
            "Illustrative only — requires a GPU. vLLM raises throughput under "
            "concurrency by packing requests (continuous batching) and paging the "
            "KV cache; the exact tokens/sec depends on model + GPU and must be "
            "benchmarked on the target, not quoted from here."
        ),
        illustrative_numbers={
            "baseline_tokens_per_s": 900,
            "vllm_tokens_per_s": 3200,
            "note": "shape only (concurrency win); measure on your own GPU",
        },
        runnable_script="scripts/bench_vllm.py",
    )


# ===========================================================================
# Convenience: one call that returns the whole measured+anchored picture.
# ===========================================================================
@dataclass
class InferenceReport:
    cache_at_095: CacheReport
    cache_at_090: CacheReport
    batching: BatchingModel
    anchored: list[AnchoredBenchmark] = field(default_factory=list)


def run_inference_report() -> InferenceReport:
    """Assemble the measured cache numbers + the modeled/anchored references."""
    return InferenceReport(
        cache_at_095=measure_cache_hit_rate(0.95),
        cache_at_090=measure_cache_hit_rate(0.90),
        batching=model_batching_throughput(),
        anchored=[quantization_reference(), vllm_reference()],
    )
