#!/usr/bin/env python3
"""Capture the output a lesson quotes, and catch it drifting.

    python course/tools/capture.py NN            # run the step's captures, write course/outputs/NN/
    python course/tools/capture.py NN --check    # write nothing; diff against what is committed

Each capture runs `bash -o pipefail -c <cmd>` in a clean environment (no API keys, a
fixed timezone, locale and hash seed) after the step's `setup`. The file is `$ <cmd>`,
then the output, normalized so that timings, memory addresses and the checkout's path
never count as a change. A manual capture (a GPU, a network, a key) is pasted by hand,
and `--check` only requires that its file exists. Stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import steps

BASELINE = {"TZ": "UTC", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0", "COLUMNS": "100", "NO_COLOR": "1",
            "DEALFINDER_ENABLE_PAID_SOURCES": "0"}
KEEP = ("PATH", "HOME", "VIRTUAL_ENV")
BUILTIN_RULES = [(re.compile(r"\x1b\[[0-9;]*[A-Za-z]"), ""),
                 (re.compile(r"in \d+(\.\d+)?s\b"), "in <t>s"),
                 (re.compile(r"0x[0-9a-f]{6,}"), "0x<addr>")]


class CaptureError(Exception):
    pass


def clean_env(manifest: steps.StepManifest, base: Mapping[str, str]) -> dict[str, str]:
    env = {k: base[k] for k in KEEP if k in base}
    env.update(BASELINE)
    if manifest.needs_db and base.get("DATABASE_URL"):
        env["DATABASE_URL"] = base["DATABASE_URL"]
    return env


def normalize(text: str, rules, repo_root: Path) -> str:
    for pattern, replace in BUILTIN_RULES:
        text = pattern.sub(replace, text)
    text = text.replace(str(Path(repo_root).resolve()), ".").replace(str(repo_root), ".")
    for pattern, replace in rules:
        text = re.sub(pattern, replace, text)
    return "\n".join(line.rstrip() for line in text.splitlines())


def _bash(cmd: str, env: dict[str, str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-o", "pipefail", "-c", cmd], cwd=cwd, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def run_setup(manifest: steps.StepManifest, repo_root: Path) -> None:
    env = clean_env(manifest, os.environ)
    for cmd in manifest.setup:
        r = _bash(cmd, env, repo_root, 600)
        if r.returncode != 0:
            raise CaptureError(f"setup `{cmd}` exited {r.returncode}:\n{r.stdout[-2000:]}")


def run_capture(manifest: steps.StepManifest, cap: steps.Capture, repo_root: Path) -> str:
    env = {**clean_env(manifest, os.environ), **cap.env}
    try:
        r = _bash(cap.cmd, env, repo_root, cap.timeout_s)
    except subprocess.TimeoutExpired:
        raise CaptureError(f"capture '{cap.name}' timed out after {cap.timeout_s}s") from None
    if r.returncode != cap.expect_exit:
        raise CaptureError(f"capture '{cap.name}' exited {r.returncode}, expected {cap.expect_exit}:\n"
                           f"{r.stdout[-2000:]}")
    return f"$ {cap.cmd}\n{normalize(r.stdout, cap.normalize, repo_root)}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("nn")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repo", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root = args.repo
    try:
        manifest = steps.load_manifest(root / f"course/steps/{args.nn}.toml")
    except (OSError, steps.ManifestError) as e:
        print(f"✗ {e}")
        return 1
    out_dir = root / f"course/outputs/{args.nn}"
    problems = 0
    try:
        if any(not c.manual for c in manifest.captures):
            run_setup(manifest, root)
        for cap in manifest.captures:
            path = out_dir / f"{cap.name}.txt"
            if cap.manual:
                if not path.exists():
                    print(f"✗ manual capture '{cap.name}' has no file: paste it into {path}, with first line "
                          f"'# manual: {cap.reason} · captured {cap.captured}'")
                    problems += 1
                continue
            text = run_capture(manifest, cap, root)
            if args.check:
                old = path.read_text() if path.exists() else ""
                if old != text:
                    print("".join(difflib.unified_diff(old.splitlines(True), text.splitlines(True),
                                                       f"committed/{path}", f"now/{path}")))
                    problems += 1
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"✓ {path}")
    except CaptureError as e:
        print(f"✗ {e}")
        return 1
    if problems:
        print(f"✗ step {args.nn}: {problems} capture(s) drifted or missing")
        return 1
    if args.check:
        print(f"✓ step {args.nn}: every capture matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
