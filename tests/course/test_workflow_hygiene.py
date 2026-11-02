"""Every workflow: no expression expanded inside a shell script, and no cron.

Line by line, without a YAML library: a `run:` value is either the rest of its line or
the block of lines indented deeper than the `run` key."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
FORBIDDEN = ("${{ github.event.", "${{ inputs.", "${{ matrix.", "${{ github.head_ref")
_RUN = re.compile(r"^(\s*)(-\s+)?run:\s*(.*)$")


def run_block_lines(paths):
    for path in paths:
        lines = path.read_text().splitlines()
        i = 0
        while i < len(lines):
            m = _RUN.match(lines[i])
            if not m:
                i += 1
                continue
            key_col = len(m.group(1)) + len(m.group(2) or "")
            value = m.group(3)
            if value and not value.startswith(("|", ">")):
                yield path, i + 1, lines[i]
                i += 1
                continue
            i += 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > key_col):
                yield path, i + 1, lines[i]
                i += 1


def test_run_block_reader_finds_block_and_inline_scripts(tmp_path):
    wf = tmp_path / "x.yml"
    wf.write_text("jobs:\n  a:\n    steps:\n      - run: echo ${{ matrix.id }}\n      - run: |\n"
                  "          echo one\n          echo ${{ github.event.pull_request.title }}\n      - name: next\n")
    found = [line.strip() for _, _, line in run_block_lines([wf])]
    assert found == ["- run: echo ${{ matrix.id }}", "echo one", "echo ${{ github.event.pull_request.title }}"]


def test_no_expression_interpolation_in_run_blocks():
    assert [f"{p.name}:{n}" for p, n, line in run_block_lines(WORKFLOWS) if any(f in line for f in FORBIDDEN)] == []


def test_no_schedule_triggers():
    assert [p.name for p in WORKFLOWS if re.search(r"^\s*schedule:", p.read_text(), re.M)] == []


def test_course_steps_plan_reads_the_pushed_or_pr_head_commit():
    # On pull_request the checkout is a merge commit with no local `course` branch,
    # so the plan job names the head commit instead of the branch.
    text = (ROOT / ".github/workflows/course-steps.yml").read_text()
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert 'steps.py verify --branch "$HEAD_SHA"' in text
    assert 'steps.py matrix --json --branch "$HEAD_SHA"' in text


def test_course_steps_workflow_reads_the_matrix():
    text = (ROOT / ".github/workflows/course-steps.yml").read_text()
    assert "fromJSON(needs.plan.outputs.matrix)" in text and "make capture-check" in text
    assert "permissions:\n  contents: read" in text and "fail-fast: false" in text
