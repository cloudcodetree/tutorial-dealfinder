"""course/tools/steps.py retag and release-check: tags follow the step commits, atomically."""
import pytest
import steps


def test_retag_dry_run_changes_nothing(git_repo):
    git_repo.step("01", lesson="a")
    assert steps.retag(git_repo.path).create == [("step-01", git_repo.git("rev-parse", "course").strip())]
    assert git_repo.git("tag", "--list") == ""


def test_retag_apply_creates_annotated_tags(git_repo):
    git_repo.step("01", lesson="a", subject="step-01: Data layer")
    steps.retag(git_repo.path, apply=True)
    assert git_repo.git("cat-file", "-t", "step-01").strip() == "tag"
    assert git_repo.git("tag", "-l", "--format=%(contents:subject)", "step-01").strip() == "step-01: Data layer"


def test_retag_moves_an_existing_tag(git_repo):
    git_repo.step("01", lesson="a")
    steps.retag(git_repo.path, apply=True)
    git_repo.git("commit", "--amend", "-m", "step-01: renamed")
    report = steps.retag(git_repo.path, apply=True)
    assert [m[0] for m in report.move] == ["step-01"]
    assert git_repo.git("rev-parse", "step-01^{commit}").strip() == git_repo.git("rev-parse", "course").strip()


def test_retag_keeps_a_tag_that_already_matches(git_repo):
    git_repo.step("01", lesson="a")
    steps.retag(git_repo.path, apply=True)
    report = steps.retag(git_repo.path, apply=True)
    assert (report.create, report.move, report.keep) == ([], [], ["step-01"])


def test_retag_is_all_or_nothing(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.commit("stray", {"x": "1"})
    with pytest.raises(steps.ChainError):
        steps.retag(git_repo.path, apply=True)
    assert git_repo.git("tag", "--list") == ""


def test_prune_only_with_flag(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.git("tag", "-a", "step-02", "-m", "old", "HEAD")
    assert steps.retag(git_repo.path, apply=True).delete == []
    assert steps.retag(git_repo.path, apply=True, prune=True).delete == ["step-02"]
    assert git_repo.git("tag", "--list", "step-02") == ""


def test_retag_refuses_after_release(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.git("tag", "-a", "course-v1", "-m", "v1", "HEAD")
    with pytest.raises(steps.RetagRefused, match="course-v1 exists: step tags are frozen"):
        steps.retag(git_repo.path, apply=True)


def test_push_requires_apply_and_is_atomic(git_repo_with_origin):
    r = git_repo_with_origin
    r.step("01", lesson="a")
    with pytest.raises(steps.RetagRefused):
        steps.retag(r.path, push=True)
    steps.retag(r.path, apply=True, push=True)
    assert "refs/tags/step-01" in r.git("ls-remote", "--tags", "origin")


def test_push_sends_tags_already_applied_locally(git_repo_with_origin):
    # The release runs retag --apply locally (release-check needs it), then --push.
    r = git_repo_with_origin
    r.step("01", lesson="a")
    steps.retag(r.path, apply=True)
    steps.retag(r.path, apply=True, push=True)
    assert "refs/tags/step-01" in r.git("ls-remote", "--tags", "origin")


def test_retag_refuses_when_the_remote_was_released(git_repo_with_origin):
    r = git_repo_with_origin
    r.step("01", lesson="a")
    r.git("tag", "-a", "course-v1", "-m", "v1", "HEAD")
    r.git("push", "-q", "origin", "refs/tags/course-v1")
    r.git("tag", "-d", "course-v1")
    with pytest.raises(steps.RetagRefused, match="course-v1"):
        steps.retag(r.path, apply=True)


def test_release_check_requires_equal_trees(git_repo):
    git_repo.step("01", lesson="a", files={"app.py": "v1"})
    git_repo.git("branch", "main")
    git_repo.git("switch", "-q", "main")
    git_repo.commit("product fix", {"app.py": "v2"})
    git_repo.git("switch", "-q", "course")
    assert "course tip tree differs from main" in steps.release_check(git_repo.path)


def test_release_check_passes_and_prints_the_commands(git_repo, capsys):
    git_repo.step("01", lesson="a", files={"app.py": "v1"})
    git_repo.git("branch", "main")
    steps.retag(git_repo.path, apply=True)
    assert steps.release_check(git_repo.path) == []
    assert steps.main(["release-check", "--repo", str(git_repo.path)]) == 0
    out = capsys.readouterr().out
    assert "git push --force-with-lease=main origin course:main" in out and "you do it" in out


def test_release_check_wants_the_tags_applied_first(git_repo):
    git_repo.step("01", lesson="a")
    git_repo.git("branch", "main")
    assert any("retag --apply" in p for p in steps.release_check(git_repo.path))
