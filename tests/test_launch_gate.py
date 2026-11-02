"""ROADMAP's launch gate: every box names proofs, and every proof it names exists."""
import re
from pathlib import Path

GATE_ID = re.compile(r"(tests/[\w/]+\.py)::(\w+)")


def _gate() -> str:
    return Path("ROADMAP.md").read_text().split("## The launch gate", 1)[1].split("\n---", 1)[0]


def test_every_gate_proof_exists():
    ids = GATE_ID.findall(_gate())
    assert len(ids) >= 6
    missing = [f"{f}::{t}" for f, t in ids if f"def {t}(" not in Path(f).read_text()]
    assert missing == []


def test_gate_matches_g5():
    gate = _gate()
    assert "Affiliate" not in gate and "no queue at launch" in gate
    assert "required only if a non-essential cookie is ever added" in gate
    boxes = [line for line in gate.splitlines() if line.startswith("- [")]
    assert len(boxes) == 6 and all("Proof:" in line for line in boxes)
    assert all(line.startswith("- [ ]") for line in boxes)   # Plan 8 checks them after the live proofs


def test_p1_progress_names_its_proofs():
    p1 = Path("ROADMAP.md").read_text().split("### P1", 1)[1].split("### P2", 1)[0]
    assert "- [x] Real consumer auth" in p1 and "- [x] Saved searches" in p1
    assert "- [ ] Price-drop **alert delivery**" in p1 and "Deferred: waits for a Best Buy key (2026-10-27)" in p1
    missing = [f"{f}::{t}" for f, t in GATE_ID.findall(p1) if f"def {t}(" not in Path(f).read_text()]
    assert missing == []


def test_monetization_is_deferred():
    p3 = Path("ROADMAP.md").read_text().split("### P3", 1)[1].split("### P4", 1)[0]
    assert "Deferred: revenue skipped (owner decision, 2026-10-25)." in p3


def test_privacy_box_proves_the_request_log_is_gone_live():
    box = next(line for line in _gate().splitlines() if line.startswith("- [ ] Privacy"))
    assert "gcloud logging read" in box and "run.googleapis.com%2Frequests" in box
