"""A throwaway git repo on a `course` branch, with fixed authors and dates so SHAs
repeat run to run, and `course/tools` importable."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "course" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Course Bot", "GIT_AUTHOR_EMAIL": "course@example.com",
    "GIT_COMMITTER_NAME": "Course Bot", "GIT_COMMITTER_EMAIL": "course@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    # The developer's own git config (signing, hooks, aliases) never reaches a test repo.
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


class GitRepo:
    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, env={**os.environ, **_GIT_ENV},
                              check=True, capture_output=True, text=True).stdout

    def _write(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            p = self.path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def commit(self, subject: str, files: dict[str, str]) -> str:
        self._write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", subject)
        return self.git("rev-parse", "HEAD").strip()

    def step(self, nn: str, lesson: str, files: dict[str, str] | None = None, subject: str | None = None,
             manifest: str | None = None) -> str:
        text = manifest if manifest is not None else f'id = "{nn}"\nlesson = "{lesson}"\ntitle = "Step {nn}"\n'
        return self.commit(subject or f"step-{nn}: {lesson}", {f"course/steps/{nn}.toml": text, **(files or {})})

    def merge(self, branch: str) -> None:
        self.git("merge", "-q", "--no-ff", "--no-edit", branch)


@pytest.fixture
def git_repo(tmp_path) -> GitRepo:
    repo = GitRepo(tmp_path)
    repo.git("init", "-q", "-b", "course")
    return repo
