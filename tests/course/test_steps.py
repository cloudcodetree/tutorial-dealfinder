"""course/tools/steps.py: manifests and the linear step chain."""
import json

import pytest
import steps


def test_verify_accepts_linear_chain(git_repo):
    git_repo.step("01", lesson="dealfinder-part-01")
    git_repo.step("02", lesson="dealfinder-part-02")
    assert steps.verify(git_repo.path) == [] and [s.id for s in steps.chain(git_repo.path)] == ["01", "02"]


def test_verify_rejects_merge(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.git("switch", "-q", "-c", "side")
    git_repo.commit("side work", {"x": "1"})
    git_repo.git("switch", "-q", "course")
    git_repo.step("02", lesson="b")
    git_repo.merge("side")
    assert any("merge commit" in p for p in steps.verify(git_repo.path))


@pytest.mark.parametrize("ids, problem", [(["01", "03"], "commit 2: expected step-02, found step-03"),
                                          (["01", "01"], "commit 2: expected step-02, found step-01")])
def test_verify_rejects_gap_and_duplicate(git_repo, ids, problem):
    for n, i in enumerate(ids):
        git_repo.step(i, lesson=f"l{n}", files={f"f{n}.txt": str(n)})
    assert problem in steps.verify(git_repo.path)


def test_verify_rejects_non_step_commit(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.commit("fix typo", {"README.md": "x"})
    assert any("not a step commit: 'fix typo'" in p for p in steps.verify(git_repo.path))


def test_verify_requires_step_manifest(git_repo):
    git_repo.commit("step-01: no manifest", {"a.py": ""})
    assert "step-01 does not add course/steps/01.toml" in steps.verify(git_repo.path)


def test_verify_lists_every_problem_in_one_pass(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.commit("wip", {"a": "1"})
    git_repo.step("05", lesson="b")
    problems = steps.verify(git_repo.path)
    assert len(problems) == 2 and "commit 2" in problems[0] and "commit 3" in problems[1]


def test_verify_rejects_a_manifest_whose_id_disagrees(git_repo):
    git_repo.step("01", lesson="a", manifest='id = "02"\nlesson = "a"\ntitle = "t"\n')
    assert any("id '02'" in p for p in steps.verify(git_repo.path))


def test_chain_raises_with_every_problem(git_repo):
    git_repo.commit("not a step", {"a": "1"})
    with pytest.raises(steps.ChainError) as e:
        steps.chain(git_repo.path)
    assert e.value.problems == ["commit 1: not a step commit: 'not a step'"]


def test_manifest_rejects_unknown_keys_and_bad_captures():
    with pytest.raises(steps.ManifestError, match="unknown key 'tset'"):
        steps.load_manifest_text('id="01"\nlesson="a"\ntitle="t"\ntset=[]', "01.toml")
    with pytest.raises(steps.ManifestError, match="manual capture 'gpu' needs reason and captured"):
        steps.load_manifest_text('id="01"\nlesson="a"\ntitle="t"\n[[capture]]\nname="gpu"\nmanual=true', "01.toml")


def test_manifest_reads_captures_and_shots():
    m = steps.load_manifest_text('''id = "01"
lesson = "dealfinder-part-01"
title = "The data layer"
needs_db = false
setup = ["true"]
tests = ["tests/test_schema.py"]
[[capture]]
name = "pytest"
cmd = "python -m pytest -q tests/test_schema.py"
normalize = [{pattern = "\\\\d+ warnings?", replace = "<n> warnings"}]
[[shot]]
name = "lab"
route = "/lab?mode=dataset"
ready = "[data-mode=dataset][data-ready=true]"
''', "01.toml")
    assert m.captures[0].cmd.startswith("python -m pytest") and m.captures[0].timeout_s == 300
    assert m.shots[0].viewport == (1280, 800) and m.tests == ("tests/test_schema.py",)


def test_matrix_json(git_repo, capsys):
    git_repo.step("01", lesson="dealfinder-part-01")
    assert steps.main(["matrix", "--json", "--repo", str(git_repo.path)]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert set(row) == {"id", "sha", "lesson", "subject", "needs_db"} and row["needs_db"] is False


def test_verify_cli(git_repo, capsys):
    git_repo.step("01", lesson="a")
    assert steps.main(["verify", "--repo", str(git_repo.path)]) == 0
    assert "✓ 1 steps, linear" in capsys.readouterr().out
