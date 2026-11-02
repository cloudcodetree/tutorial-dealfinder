"""course/tools/capture.py and check.py: outputs captured in a clean env, drift caught,
durations ignored, learner checkpoints."""
import os
import subprocess
import sys
from pathlib import Path

import capture
import check
import pytest
import steps


class TmpStep:
    """course/steps/01.toml in a temp repo. Its one capture, `out`, prints out.txt."""

    def __init__(self, root: Path):
        self.root = root
        self.cmd = "cat out.txt"
        self.manual: list[tuple[str, str, str]] = []
        self.tests: list[str] = []
        self._write()

    def _write(self):
        text = 'id = "01"\nlesson = "dealfinder-part-01"\ntitle = "The data layer"\n'
        if self.tests:
            text += "tests = [" + ", ".join(f'"{t}"' for t in self.tests) + "]\n"
        text += f'[[capture]]\nname = "out"\ncmd = "{self.cmd}"\n'
        for name, reason, captured in self.manual:
            text += f'[[capture]]\nname = "{name}"\nmanual = true\nreason = "{reason}"\ncaptured = "{captured}"\n'
        path = self.root / "course/steps/01.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    @property
    def manifest(self):
        return steps.load_manifest(self.root / "course/steps/01.toml")

    def set_output(self, text: str):
        (self.root / "out.txt").write_text(text + "\n")

    def set_cmd(self, cmd: str):
        self.cmd = cmd
        self._write()

    def add_manual(self, name, reason, captured):
        self.manual.append((name, reason, captured))
        self._write()

    def write_output(self, name, text):
        path = self.root / f"course/outputs/01/{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")

    def add_passing_test(self):
        (self.root / "tests").mkdir(exist_ok=True)
        (self.root / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n")
        self.tests.append("tests/test_ok.py")
        self._write()

    def add_failing_test(self):
        (self.root / "tests").mkdir(exist_ok=True)
        (self.root / "tests/test_bad.py").write_text("def test_bad():\n    assert False\n")
        self.tests.append("tests/test_bad.py")
        self._write()


@pytest.fixture
def tmp_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    step = TmpStep(tmp_path)
    step.set_output("hello")
    return step


def test_normalize_durations_and_paths(tmp_path):
    out = capture.normalize(f"6 passed in 0.42s\n{tmp_path}/tests/a.py  \n\x1b[32mok\x1b[0m", [], tmp_path)
    assert out == "6 passed in <t>s\n./tests/a.py\nok"


def test_normalize_addresses_and_capture_rules(tmp_path):
    out = capture.normalize("<obj at 0x7f3a9c2b10>\n3 warnings", [(r"\d+ warnings?", "<n> warnings")], tmp_path)
    assert out == "<obj at 0x<addr>>\n<n> warnings"


def test_capture_writes_the_command_then_the_output(tmp_step):
    tmp_step.set_output("6 passed in 0.42s")
    assert capture.main(["01"]) == 0
    assert (tmp_step.root / "course/outputs/01/out.txt").read_text() == "$ cat out.txt\n6 passed in <t>s\n"


def test_check_ignores_durations(tmp_step):
    tmp_step.set_output("6 passed in 0.42s")
    assert capture.main(["01"]) == 0
    tmp_step.set_output("6 passed in 1.97s")
    assert capture.main(["01", "--check"]) == 0


def test_check_fails_on_real_change(tmp_step, capsys):
    tmp_step.set_output("6 passed in 0.42s")
    capture.main(["01"])
    tmp_step.set_output("5 passed, 1 failed in 0.40s")
    assert capture.main(["01", "--check"]) == 1 and "-6 passed in <t>s" in capsys.readouterr().out


def test_check_writes_nothing(tmp_step):
    tmp_step.set_output("one")
    capture.main(["01"])
    tmp_step.set_output("two")
    capture.main(["01", "--check"])
    assert "one" in (tmp_step.root / "course/outputs/01/out.txt").read_text()


def test_check_fails_when_an_output_was_never_captured(tmp_step):
    assert capture.main(["01", "--check"]) == 1


def test_manual_capture_skipped_but_required(tmp_step):
    capture.main(["01"])
    tmp_step.add_manual("colab-train", reason="needs a Colab T4 GPU", captured="2026-10-20")
    assert capture.main(["01", "--check"]) == 1
    tmp_step.write_output("colab-train", "# manual: needs a Colab T4 GPU · captured 2026-10-20\nloss 0.41")
    assert capture.main(["01", "--check"]) == 0


def test_clean_env_drops_keys(tmp_step):
    env = capture.clean_env(tmp_step.manifest, {"PATH": "/bin", "BESTBUY_API_KEY": "k", "DATABASE_URL": "x"})
    assert "BESTBUY_API_KEY" not in env and "DATABASE_URL" not in env and env["TZ"] == "UTC"
    assert env["DEALFINDER_ENABLE_PAID_SOURCES"] == "0" and env["PATH"] == "/bin"


def test_clean_env_disables_dotenv(tmp_step):
    # dealfinder/__init__ calls load_dotenv(), which searches every parent directory:
    # a step tree inside another checkout would read that checkout's .env and secrets.
    env = capture.clean_env(tmp_step.manifest, {"PATH": "/bin"})
    assert env["PYTHON_DOTENV_DISABLED"] == "1"


def test_a_capture_sees_no_key_from_the_shell(tmp_step, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    tmp_step.set_cmd('echo key=${OPENROUTER_API_KEY:-none}')
    capture.main(["01"])
    assert "key=none" in (tmp_step.root / "course/outputs/01/out.txt").read_text()


def test_exit_code_mismatch_fails(tmp_step):
    tmp_step.set_cmd("exit 3")
    assert capture.main(["01"]) == 1


def test_check_cli_reports_checkpoint(tmp_step, capsys):
    tmp_step.add_passing_test()
    assert check.main(["01"]) == 0
    assert "✓ Part 01 checkpoint: The data layer (1 passed)" in capsys.readouterr().out


def test_check_cli_names_the_reference_on_failure(tmp_step, capsys):
    tmp_step.add_failing_test()
    assert check.main(["01"]) == 1
    assert "✗ Part 01 checkpoint failed. Compare with: git diff step-01 -- tests/test_bad.py" in capsys.readouterr().out


def test_make_check_without_a_step_prints_usage():
    make = "/usr/bin/make" if Path("/usr/bin/make").exists() else "make"
    # The course-steps job sets STEP for its own make calls; make would read it from the env.
    env = {k: v for k, v in os.environ.items() if k != "STEP"}
    r = subprocess.run([make, "-s", "check"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
                       env=env)
    assert r.returncode == 2 and "usage: make check STEP=NN" in r.stdout


def test_tools_import_only_the_standard_library():
    # They run before any install, so every import is stdlib or a sibling tool.
    import ast
    tools = Path(__file__).resolve().parents[2] / "course/tools"
    allowed = set(sys.stdlib_module_names) | {"__future__", "steps", "capture", "check"}
    for path in tools.glob("*.py"):
        tree = ast.parse(path.read_text())
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
        assert mods <= allowed, f"{path.name}: {sorted(mods - allowed)}"


def test_dotenv_honours_the_disable_switch():
    # PYTHON_DOTENV_DISABLED is only read by python-dotenv 1.2.4 and later (checked in
    # its source); an older install would still load a parent .env.
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    assert '"python-dotenv>=1.2.4"' in pyproject
