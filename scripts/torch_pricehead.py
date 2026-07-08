#!/usr/bin/env python
"""Run the real PyTorch MLP price-head training loop and print its metrics.

This is a thin CLI over ``dealfinder.models.train_torch_pricehead`` — the actual
autograd loop lives in the package (and is test-pinned) because torch installs
cleanly in this venv. The script exists so the loop is trivially runnable on any
machine that has torch:

    python scripts/torch_pricehead.py

It prints the train/test sizes, the deterministic test MAE (in dollars), and the
final training loss. Everything is seeded, so a given environment reproduces the
same numbers.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        import torch  # noqa: F401
    except ImportError:
        print("torch is not installed. Install the CPU wheel: pip install torch")
        return 1

    from dealfinder.models import train_torch_pricehead

    r = train_torch_pricehead()
    print("PyTorch MLP price head (real training loop)")
    print(f"  train / test rows : {r.n_train} / {r.n_test}")
    print(f"  epochs            : {r.epochs}")
    print(f"  test MAE          : ${r.mae:.2f}")
    print(f"  final train loss  : {r.final_loss:.5f} (standardized MSE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
