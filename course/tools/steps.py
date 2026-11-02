#!/usr/bin/env python3
"""The course's step chain: one `step-NN:` commit per lesson on the `course` branch.

    python course/tools/steps.py verify [--repo .] [--branch course]
    python course/tools/steps.py matrix --json [--repo .] [--branch course]
    python course/tools/steps.py manifest NN --json [--repo .]

`course` is orphan-rooted and linear. Commit N is `step-NN: …`, adds
`course/steps/NN.toml`, and has exactly one parent (the root has none). `verify`
lists every problem in one pass, numbered by commit position. Stdlib only, so it runs
before any install.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

SUBJECT = re.compile(r"^step-(\d{2}): .+$")
NAME = re.compile(r"^[a-z0-9-]+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_KEYS = {"id", "lesson", "title", "needs_db", "setup", "tests", "capture", "shot"}
CAPTURE_KEYS = {"name", "cmd", "manual", "reason", "captured", "normalize", "env", "timeout_s", "expect_exit"}
SHOT_KEYS = {"name", "route", "ready", "highlight", "mask", "viewport", "full_page"}


class ManifestError(ValueError):
    pass


class ChainError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Capture:
    name: str
    cmd: str | None = None
    manual: bool = False
    reason: str | None = None
    captured: str | None = None
    normalize: tuple[tuple[str, str], ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 300
    expect_exit: int = 0


@dataclass(frozen=True)
class Shot:
    name: str
    route: str
    ready: str
    highlight: tuple[str, ...] = ()
    mask: tuple[str, ...] = ()
    viewport: tuple[int, int] = (1280, 800)
    full_page: bool = False


@dataclass(frozen=True)
class StepManifest:
    id: str
    lesson: str
    title: str
    needs_db: bool = False
    setup: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    captures: tuple[Capture, ...] = ()
    shots: tuple[Shot, ...] = ()


@dataclass(frozen=True)
class StepCommit:
    id: str
    sha: str
    subject: str
    manifest: StepManifest


# ── manifests ───────────────────────────────────────────────────────────────
def _unknown(table: dict, allowed: set[str], where: str) -> None:
    for key in table:
        if key not in allowed:
            raise ManifestError(f"{where}: unknown key '{key}'")


def _strs(value, what: str, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"{where}: {what} must be a list of strings")
    return tuple(value)


def _capture(raw: dict, where: str) -> Capture:
    _unknown(raw, CAPTURE_KEYS, where)
    name = raw.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ManifestError(f"{where}: capture name must match [a-z0-9-]+, got {name!r}")
    manual = bool(raw.get("manual", False))
    if manual and not (raw.get("reason") and DATE.match(str(raw.get("captured", "")))):
        raise ManifestError(f"{where}: manual capture '{name}' needs reason and captured (YYYY-MM-DD)")
    if not manual and not raw.get("cmd"):
        raise ManifestError(f"{where}: capture '{name}' needs cmd (or manual = true)")
    rules = []
    for rule in raw.get("normalize", []):
        if not isinstance(rule, dict) or set(rule) != {"pattern", "replace"}:
            raise ManifestError(f"{where}: capture '{name}' normalize rules are {{pattern, replace}}")
        try:
            re.compile(rule["pattern"])
        except re.error as e:
            raise ManifestError(f"{where}: capture '{name}' pattern {rule['pattern']!r}: {e}") from None
        rules.append((rule["pattern"], rule["replace"]))
    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise ManifestError(f"{where}: capture '{name}' env must map names to strings")
    return Capture(name=name, cmd=raw.get("cmd"), manual=manual, reason=raw.get("reason"),
                   captured=raw.get("captured"), normalize=tuple(rules), env=dict(env),
                   timeout_s=int(raw.get("timeout_s", 300)), expect_exit=int(raw.get("expect_exit", 0)))


def _shot(raw: dict, where: str) -> Shot:
    _unknown(raw, SHOT_KEYS, where)
    name = raw.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ManifestError(f"{where}: shot name must match [a-z0-9-]+, got {name!r}")
    route, ready = raw.get("route"), raw.get("ready")
    if not isinstance(route, str) or not route.startswith("/") or not isinstance(ready, str) or not ready:
        raise ManifestError(f"{where}: shot '{name}' needs a route starting with / and a ready selector")
    vp = raw.get("viewport", {"width": 1280, "height": 800})
    if not isinstance(vp, dict) or set(vp) != {"width", "height"}:
        raise ManifestError(f"{where}: shot '{name}' viewport is {{width, height}}")
    return Shot(name=name, route=route, ready=ready,
                highlight=_strs(raw.get("highlight", []), "highlight", where),
                mask=_strs(raw.get("mask", []), "mask", where),
                viewport=(int(vp["width"]), int(vp["height"])), full_page=bool(raw.get("full_page", False)))


def load_manifest_text(text: str, where: str) -> StepManifest:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{where}: {e}") from None
    _unknown(raw, TOP_KEYS, where)
    for key in ("id", "lesson", "title"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ManifestError(f"{where}: {key} is required")
    if not re.fullmatch(r"\d{2}", raw["id"]):
        raise ManifestError(f"{where}: id must be two digits, got {raw['id']!r}")
    captures = tuple(_capture(c, where) for c in raw.get("capture", []))
    shots = tuple(_shot(s, where) for s in raw.get("shot", []))
    for kind, items in (("capture", captures), ("shot", shots)):
        names = [i.name for i in items]
        if len(names) != len(set(names)):
            raise ManifestError(f"{where}: duplicate {kind} name")
    return StepManifest(id=raw["id"], lesson=raw["lesson"], title=raw["title"],
                        needs_db=bool(raw.get("needs_db", False)),
                        setup=_strs(raw.get("setup", []), "setup", where),
                        tests=_strs(raw.get("tests", []), "tests", where), captures=captures, shots=shots)


def load_manifest(path: Path) -> StepManifest:
    return load_manifest_text(Path(path).read_text(), str(path))


# ── the chain ───────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _added(repo: Path, sha: str) -> set[str]:
    out = _git(repo, "diff-tree", "-r", "--root", "--no-commit-id", "--name-status", sha)
    return {line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("A\t")}


def chain(repo: Path, branch: str = "course") -> list[StepCommit]:
    """Every step commit, oldest first. Raises ChainError listing every problem."""
    try:
        # "--": the branch `course` is also a directory in its own tree.
        log = _git(repo, "log", "--reverse", "--format=%H%x00%P%x00%s", branch, "--")
    except subprocess.CalledProcessError:
        raise ChainError([f"no branch {branch!r}"]) from None
    problems: list[str] = []
    commits: list[StepCommit] = []
    for pos, line in enumerate(log.splitlines(), 1):
        sha, parents, subject = line.split("\x00", 2)
        if len(parents.split()) > 1:
            problems.append(f"commit {pos}: merge commit {sha[:7]} ({subject!r})")
            continue
        m = SUBJECT.match(subject)
        if not m:
            problems.append(f"commit {pos}: not a step commit: {subject!r}")
            continue
        nn, expected = m.group(1), f"{pos:02d}"
        if nn != expected:
            problems.append(f"commit {pos}: expected step-{expected}, found step-{nn}")
            continue
        path = f"course/steps/{nn}.toml"
        if path not in _added(repo, sha):
            problems.append(f"step-{nn} does not add {path}")
            continue
        try:
            manifest = load_manifest_text(_git(repo, "show", f"{sha}:{path}"), f"step-{nn} {path}")
        except ManifestError as e:
            problems.append(str(e))
            continue
        if manifest.id != nn:
            problems.append(f"step-{nn} {path}: id '{manifest.id}' does not match the step")
            continue
        commits.append(StepCommit(id=nn, sha=sha, subject=subject, manifest=manifest))
    if problems:
        raise ChainError(problems)
    return commits


def verify(repo: Path, branch: str = "course") -> list[str]:
    try:
        chain(repo, branch)
    except ChainError as e:
        return e.problems
    return []


# ── CLI ─────────────────────────────────────────────────────────────────────
def _jsonable(manifest: StepManifest) -> dict:
    out = asdict(manifest)
    for cap in out["captures"]:
        cap["normalize"] = [{"pattern": p, "replace": r} for p, r in cap["normalize"]]
    for shot in out["shots"]:
        shot["viewport"] = {"width": shot["viewport"][0], "height": shot["viewport"][1]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "matrix", "manifest"):
        p = sub.add_parser(name)
        p.add_argument("--repo", type=Path, default=Path("."))
        p.add_argument("--branch", default="course")
        if name != "verify":
            p.add_argument("--json", action="store_true", required=True)
    sub.choices["manifest"].add_argument("nn")
    args = ap.parse_args(argv)

    if args.cmd == "manifest":
        try:
            print(json.dumps(_jsonable(load_manifest(args.repo / f"course/steps/{args.nn}.toml")), indent=2))
        except (OSError, ManifestError) as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        return 0
    try:
        commits = chain(args.repo, args.branch)
    except ChainError as e:
        for problem in e.problems:
            print(f"✗ {problem}", file=sys.stdout if args.cmd == "verify" else sys.stderr)
        return 1
    if args.cmd == "verify":
        print(f"✓ {len(commits)} steps, linear")
        return 0
    print(json.dumps([{"id": c.id, "sha": c.sha, "lesson": c.manifest.lesson, "subject": c.subject,
                       "needs_db": c.manifest.needs_db} for c in commits]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
