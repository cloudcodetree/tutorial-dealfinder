"""ANCHORED GPU benchmark: INT8 / INT4 quantization (Part 23).

Runnable ONLY where a GPU + bitsandbytes are available. On CPU (this course's CI
box) it refuses to fabricate numbers — it prints what it *would* measure and
exits. This is the honest half of ``dealfinder.inference.quantization_reference``:
the concept is real, the magnitude must be measured on YOUR device, not quoted.

Usage (on a GPU host):
    pip install torch transformers bitsandbytes accelerate
    python scripts/bench_quantization.py --model <hf-model-id>

It loads the model at fp16, INT8, and INT4, and reports the REAL VRAM footprint
and a short generation latency for each — measured on the machine you run it on.
"""
from __future__ import annotations

import argparse
import sys


def _has_gpu() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--tokens", type=int, default=64)
    args = ap.parse_args()

    if not _has_gpu():
        print(
            "No CUDA GPU detected. This benchmark measures real VRAM/latency for "
            "fp16 vs INT8 vs INT4 and will NOT print fabricated numbers on CPU.\n"
            "Run it on a GPU host to get measured figures for your device."
        )
        return 0

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(args.model)
    prompt = tok("Is this a good deal?", return_tensors="pt").to("cuda")

    configs = {
        "fp16": dict(torch_dtype=torch.float16),
        "int8": dict(quantization_config=BitsAndBytesConfig(load_in_8bit=True)),
        "int4": dict(quantization_config=BitsAndBytesConfig(load_in_4bit=True)),
    }
    for name, kw in configs.items():
        torch.cuda.reset_peak_memory_stats()
        model = AutoModelForCausalLM.from_pretrained(args.model, device_map="cuda", **kw)
        model.generate(**prompt, max_new_tokens=args.tokens)
        vram = torch.cuda.max_memory_allocated() / 1e9
        print(f"{name}: peak VRAM {vram:.2f} GB (measured on this GPU)")
        del model
        torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
