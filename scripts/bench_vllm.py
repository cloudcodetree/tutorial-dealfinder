"""ANCHORED GPU benchmark: vLLM continuous batching / PagedAttention (Part 23).

Runnable ONLY where a GPU + vLLM are available. On CPU (this course's CI box) it
refuses to fabricate numbers — it prints what it *would* measure and exits. This
is the honest half of ``dealfinder.inference.vllm_reference``: vLLM's throughput
win under concurrency is real, but the magnitude is device/model specific and must
be measured on YOUR hardware, not quoted.

Usage (on a GPU host):
    pip install vllm
    python scripts/bench_vllm.py --model <hf-model-id> --concurrency 64

It drives N concurrent generations through vLLM's engine and reports the REAL
aggregate tokens/sec measured on the machine you run it on.
"""
from __future__ import annotations

import argparse
import sys
import time


def _has_gpu() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--tokens", type=int, default=128)
    args = ap.parse_args()

    if not _has_gpu():
        print(
            "No CUDA GPU detected. This benchmark measures real aggregate "
            "tokens/sec under concurrency and will NOT print fabricated numbers on "
            "CPU.\nRun it on a GPU host to get measured figures for your device."
        )
        return 0

    from vllm import LLM, SamplingParams

    llm = LLM(model=args.model)
    prompts = ["Is this a good deal? Explain briefly."] * args.concurrency
    params = SamplingParams(max_tokens=args.tokens)

    t0 = time.perf_counter()
    outputs = llm.generate(prompts, params)
    dt = time.perf_counter() - t0
    total_tokens = sum(len(o.outputs[0].token_ids) for o in outputs)
    print(
        f"vLLM: {total_tokens} tokens in {dt:.2f}s = "
        f"{total_tokens / dt:.0f} tokens/sec (measured on this GPU, "
        f"concurrency={args.concurrency})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
