"""CLI tests for ``finish``: scratch repos with a bare remote and a fake ``gh``."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from planners.cli import app
from planners.finish import PullRequest, merge_subject
from tests.helpers import commit_all, git_out, init_git

runner = CliRunner()

_BRANCH = "feature/my-thing"
_URL = "https://github.com/owner/repo/pull/7"
_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: {status}\nbranch: feature/my-thing\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:{concluded}\npr:{pr}\n---\n\n"
    "# My thing\n\n## Plan\n\nBody.\n\n"
    "## Log\n\n- **2026-06-08T12:00:00-07:00** — Activated.\n"
    "  - Branch: `feature/my-thing`\n  - Base: `main` at `0000000`\n"
    "  - Worktree: `.worktrees/my-thing`\n  - PR: pending\n"
)


def _plan_text(status: str, pr: str | None = "", concluded: str = "") -> str:
    shown = " null" if pr is None else (f" {pr}" if pr else "")
    return _PLAN.format(
        status=status, pr=shown, concluded=f" {concluded}" if concluded else ""
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _index(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(cwd)
    result = runner.invoke(app, ["index", "."])
    assert result.exit_code == 0, result.output


class Scene:
    """A repo on ``main`` with plan 005 closed on its branch, in a worktree."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        pr: str | None = _URL,
        status: str = "done",
        reindex_branch: bool = True,
    ) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "repo"
        self.remote = tmp_path / "remote.git"
        self.worktree = self.root / ".worktrees" / "my-thing"
        self.state = tmp_path / "gh"
        self.state.mkdir()
        self.monkeypatch = monkeypatch

        self.root.mkdir()
        init_git(self.root)
        plan = self.root / ".planners" / "plans" / "005-my-thing" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(_plan_text("active"), encoding="utf-8")
        (self.root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
        _index(self.root, monkeypatch)
        commit_all(self.root, "plan [activate]: 005 - my-thing")
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        _git(self.root, "remote", "add", "origin", str(self.remote))
        _git(self.root, "push", "-qu", "origin", "main")

        _git(self.root, "worktree", "add", "-q", str(self.worktree), "-b", _BRANCH)
        (self.worktree / "work.txt").write_text("work\n", encoding="utf-8")
        commit_all(self.worktree, "work")
        closed = self.worktree / ".planners" / "plans" / "005-my-thing" / "plan.md"
        closed.write_text(
            _plan_text(status, pr, "2026-06-09T12:00:00-07:00"), encoding="utf-8"
        )
        if reindex_branch:
            _index(self.worktree, monkeypatch)
        commit_all(self.worktree, "plan [close]: 005 - my-thing")
        _git(self.worktree, "push", "-qu", "origin", _BRANCH)

        # The clone the fake gh merges in, standing in for GitHub's merge.
        merger = self.state / "merger"
        subprocess.run(
            ["git", "clone", "-q", "-b", "main", str(self.remote), str(merger)],
            check=True,
            capture_output=True,
        )
        init_git_identity(merger)
        self.set_view(_pr())
        (self.state / "merged.json").write_text(
            json.dumps(_pr("MERGED")), encoding="utf-8"
        )
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        _script(
            self.bin / "gh",
            f'd="{self.state}"\n'
            'echo "$@" >> "$d/calls"\n'
            'case "$1 $2" in\n'
            '"pr view")\n'
            '  n=$(cat "$d/count" 2>/dev/null || echo 0); n=$((n+1)); '
            'echo $n > "$d/count"\n'
            '  if [ -f "$d/merged" ]; then cat "$d/merged.json"\n'
            '  elif [ -f "$d/view.$n" ]; then cat "$d/view.$n"\n'
            '  else cat "$d/view"; fi ;;\n'
            '"pr merge")\n'
            '  git -C "$d/merger" fetch -q origin'
            f' && git -C "$d/merger" merge -q --no-ff origin/{_BRANCH} -m merged'
            ' && git -C "$d/merger" push -q origin HEAD:main'
            ' && touch "$d/merged" ;;\n'
            "esac\n",
        )
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.chdir(self.root)

    def set_view(self, data: dict[str, object], n: int | None = None) -> None:
        name = "view" if n is None else f"view.{n}"
        (self.state / name).write_text(json.dumps(data), encoding="utf-8")

    def merge_on_github(self) -> None:
        subprocess.run(
            ["gh", "pr", "merge", "7"], check=True, env={**os.environ}, cwd=self.root
        )
        (self.state / "calls").unlink()

    def calls(self) -> list[str]:
        path = self.state / "calls"
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def merges(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("pr merge")]

    def finish(self, *args: str) -> Result:
        return runner.invoke(app, ["finish", "005", *args], catch_exceptions=False)

    def has_branch(self, ref: str) -> bool:
        return (
            subprocess.run(
                ["git", "rev-parse", "--verify", "-q", ref],
                cwd=self.root,
                capture_output=True,
            ).returncode
            == 0
        )


def init_git_identity(path: Path) -> None:
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _pr(state: str = "OPEN", *, fork: bool = False) -> dict[str, object]:
    return {
        "number": 7,
        "state": state,
        "baseRefName": "main",
        "headRefName": _BRANCH,
        "isCrossRepository": fork,
        "headRepositoryOwner": {"login": "owner"},
    }


def _assert_finished(scene: Scene, *, published: bool = True) -> None:
    root = scene.root
    assert not scene.worktree.exists()
    assert not scene.has_branch(f"refs/heads/{_BRANCH}")
    assert not git_out(root, "ls-remote", "--heads", "origin", _BRANCH).strip()
    assert git_out(root, "branch", "--show-current").strip() == "main"
    if published:
        assert git_out(root, "rev-parse", "HEAD") == git_out(
            root, "rev-parse", "origin/main"
        )
    assert (root / "work.txt").is_file()
    assert git_out(root, "status", "--porcelain") == ""


def _assert_untouched(scene: Scene) -> None:
    assert scene.worktree.is_dir()
    assert scene.has_branch(f"refs/heads/{_BRANCH}")
    assert git_out(scene.root, "ls-remote", "--heads", "origin", _BRANCH).strip()


def test_finish_cleans_up_after_a_merged_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    result = scene.finish()
    assert result.exit_code == 0, result.output
    _assert_finished(scene)
    # finish reads the PR and never merges it: the merge is the session's call.
    assert scene.merges() == []
    for line in (
        f"plan 005: {_BRANCH} is merged into main by PR #7",
        "removed the worktree .worktrees/my-thing",
        "pulled main",
        f"deleted {_BRANCH} on origin",
        f"deleted {_BRANCH} locally",
        "finished plan 005",
    ):
        assert line in result.output
    # The index was current on the branch, so the merge left nothing to commit.
    assert "plan index" not in result.output


def test_finish_twice_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    assert scene.finish().exit_code == 0
    head = git_out(scene.root, "rev-parse", "HEAD")
    again = scene.finish()
    assert again.exit_code == 0, again.output
    assert f"no worktree has {_BRANCH} checked out" in again.output
    assert f"{_BRANCH} is already gone from origin" in again.output
    assert f"{_BRANCH} is already gone locally" in again.output
    assert git_out(scene.root, "rev-parse", "HEAD") == head
    _assert_finished(scene)


def test_finish_without_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    _git(scene.root, "worktree", "remove", str(scene.worktree))
    scene.merge_on_github()
    result = scene.finish()
    assert result.exit_code == 0, result.output
    assert f"no worktree has {_BRANCH} checked out" in result.output
    _assert_finished(scene)


def test_finish_stops_on_an_open_pr_and_names_the_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    result = scene.finish()
    assert result.exit_code == 1
    assert "PR #7 is not merged yet" in result.output
    assert (
        f'gh pr merge 7 --merge --subject "merge: PR #7 - {_BRANCH}"' in result.output
    )
    assert scene.merges() == []
    _assert_untouched(scene)


def test_finish_stops_on_a_closed_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.set_view(_pr("CLOSED"))
    result = scene.finish()
    assert result.exit_code == 1
    assert "PR #7 is closed without being merged" in result.output
    _assert_untouched(scene)


def test_finish_commits_an_index_the_merge_left_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, reindex_branch=False)
    scene.merge_on_github()
    result = scene.finish()
    assert result.exit_code == 0, result.output
    assert "committed the regenerated plan index; push main" in result.output
    assert git_out(scene.root, "log", "-1", "--format=%s").strip() == (
        "update plan index after merge"
    )
    readme = (scene.root / ".planners" / "README.md").read_text(encoding="utf-8")
    assert "| done |" in readme
    # finish publishes no code, so the commit waits for the session's push.
    assert git_out(scene.root, "rev-list", "--count", "origin/main..main") == "1\n"
    _assert_finished(scene, published=False)


def test_finish_stops_on_a_dirty_worktree_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    loose = scene.worktree / "loose.txt"
    loose.write_text("loose\n", encoding="utf-8")
    first = scene.finish()
    assert first.exit_code == 1
    assert "1 uncommitted change(s)" in first.output
    _assert_untouched(scene)

    loose.unlink()
    second = scene.finish()
    assert second.exit_code == 0, second.output
    _assert_finished(scene)


def test_finish_stops_on_unpushed_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    (scene.worktree / "late.txt").write_text("late\n", encoding="utf-8")
    commit_all(scene.worktree, "late")
    result = scene.finish()
    assert result.exit_code == 1
    assert f"1 commit(s) not pushed to origin/{_BRANCH}" in result.output
    _assert_untouched(scene)


def test_finish_stops_on_a_branch_the_base_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    _git(scene.root, "worktree", "remove", str(scene.worktree))
    scene.merge_on_github()
    # A commit on the local branch that the PR never carried.
    _git(scene.root, "checkout", "-q", _BRANCH)
    (scene.root / "stray.txt").write_text("stray\n", encoding="utf-8")
    commit_all(scene.root, "stray")
    _git(scene.root, "checkout", "-q", "main")
    result = scene.finish()
    assert result.exit_code == 1
    assert f"{_BRANCH} holds commits main does not" in result.output
    assert scene.has_branch(f"refs/heads/{_BRANCH}")


def test_finish_stops_on_a_plan_that_is_not_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, status="implemented")
    result = scene.finish()
    assert result.exit_code == 1
    assert f"plan 005 is implemented on {_BRANCH}" in result.output
    assert scene.calls() == []


def test_finish_stops_inside_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    monkeypatch.chdir(scene.worktree)
    result = scene.finish()
    assert result.exit_code == 1
    assert "this is the worktree being removed" in result.output
    assert scene.worktree.is_dir()


@pytest.mark.parametrize("flag", [False, True])
def test_finish_after_a_local_merge(
    flag: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `pr: null` takes the local path on its own; --no-pr takes it with a PR set.
    scene = Scene(tmp_path, monkeypatch, pr=_URL if flag else None)
    args = ["--no-pr"] if flag else []

    unmerged = scene.finish(*args)
    assert unmerged.exit_code == 1
    assert f"{_BRANCH} is not merged into main yet" in unmerged.output
    assert (
        f'git merge --no-ff {_BRANCH} -m "merge: {_BRANCH}" && git push'
        in unmerged.output
    )
    _assert_untouched(scene)

    _git(scene.root, "merge", "--no-ff", _BRANCH, "-m", f"merge: {_BRANCH}")
    _git(scene.root, "push", "-q")
    result = scene.finish(*args)
    assert result.exit_code == 0, result.output
    assert f"{_BRANCH} is merged into main by a local merge" in result.output
    assert scene.calls() == []
    _assert_finished(scene)


def test_finish_repoints_a_hook_installed_from_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch)
    scene.merge_on_github()
    hooks = scene.root / ".git" / "hooks"
    python = scene.worktree / ".venv" / "bin" / "python"
    _script(hooks / "pre-commit", f"INSTALL_PYTHON={python}\nexit 0\n")
    _script(hooks / "post-merge", "INSTALL_PYTHON=/usr/bin/python3\nexit 0\n")
    uv_calls = tmp_path / "uv-calls"
    _script(scene.bin / "uv", f'echo "$@" >> "{uv_calls}"\n')
    result = scene.finish()
    assert result.exit_code == 0, result.output
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [
        "run pre-commit install --hook-type pre-commit"
    ]
    assert "re-installed the pre-commit hook" in result.output


def test_merge_subject_truncates_the_label() -> None:
    assert merge_subject(_BRANCH, 7) == f"merge: PR #7 - {_BRANCH}"
    assert merge_subject(_BRANCH) == f"merge: {_BRANCH}"
    long = "feature/install-activate-precommit-hook-from-the-main-checkout"
    subject = merge_subject(long, 6)
    assert len(subject) == 60
    assert subject == "merge: PR #6 - feature/install-activate-precommit-hook-fr..."


def test_pull_request_names_a_fork_by_owner() -> None:
    assert PullRequest.from_json(_pr()).label == _BRANCH
    assert PullRequest.from_json(_pr(fork=True)).label == f"owner/{_BRANCH}"
