#!/usr/bin/env python3
"""A learner checkpoint: run one step's tests against your code.

    python course/tools/check.py NN        # or: make check STEP=NN

It runs the step's `setup`, then `python -m pytest -q <the step's tests>`. On a pass it
prints `✓ Part NN checkpoint: <title> (<n> passed)`. On a failure it names the tests to
compare with the reference code at the step's tag. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import capture
import steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("nn")
    ap.add_argument("--repo", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    try:
        manifest = steps.load_manifest(args.repo / f"course/steps/{args.nn}.toml")
    except (OSError, steps.ManifestError) as e:
        print(f"✗ {e}")
        return 1
    if not manifest.tests:
        print(f"✓ Part {args.nn} is a concept lesson: there is no code to check.")
        return 0
    try:
        capture.run_setup(manifest, args.repo)
    except capture.CaptureError as e:
        print(f"✗ {e}")
        return 1
    env = {**capture.clean_env(manifest, os.environ), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *manifest.tests],
                       cwd=args.repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    passed = re.search(r"(\d+) passed", r.stdout)
    if r.returncode == 0:
        print(f"✓ Part {args.nn} checkpoint: {manifest.title} ({passed.group(1) if passed else 0} passed)")
        return 0
    print(r.stdout[-4000:])
    failing = sorted({m.group(1) for m in re.finditer(r"^(?:FAILED|ERROR) ([^:\s]+)", r.stdout, re.M)})
    print(f"✗ Part {args.nn} checkpoint failed. Compare with: git diff step-{args.nn} -- "
          f"{' '.join(failing or manifest.tests)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
