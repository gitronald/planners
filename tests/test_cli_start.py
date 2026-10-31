"""CLI tests for ``start``: scratch repos with a bare remote and a fake ``gh``.

Every step is exercised the way a real interruption reaches it: a run stops there,
whatever stopped it is dealt with, and a re-run picks up without repeating the work
before it.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from planners.cli import app
from tests.helpers import (
    bare_remote,
    commit_all,
    git,
    git_out,
    init_git,
    set_identity,
    write_script,
)

runner = CliRunner()

_BRANCH = "feature/005-my-thing"
_TREE = ".worktrees/005-my-thing"
_URL = "https://github.com/owner/repo/pull/7"
_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: {status}\nbranch:\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:{concluded}\npr:\n---\n\n"
    "# My thing\n\n## Plan\n\nBody.\n"
)
_REL_PLAN = Path(".planners/plans/005-my-thing/plan.md")


class Scene:
    """A repo on ``main`` holding draft plan 005, with ``origin`` of a given kind."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        kind: str | None = "github",
        status: str = "draft",
        ignore: bool = True,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.root = tmp_path / "repo"
        self.remote = tmp_path / "remote.git"
        self.root.mkdir()
        init_git(self.root)
        self.plan = self.root / _REL_PLAN
        self.plan.parent.mkdir(parents=True)
        concluded = " 2026-06-09T12:00:00-07:00" if status == "done" else ""
        self.plan.write_text(
            _PLAN.format(status=status, concluded=concluded), encoding="utf-8"
        )
        if ignore:
            (self.root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
        commit_all(self.root, "initial commit")
        if kind is not None:
            bare_remote(self.root, self.remote)
            git(self.root, "push", "-qu", "origin", "main")
            git(self.root, "config", "planners.remoteKind", kind)
        self.gh_calls = tmp_path / "gh-calls.txt"
        self.gh_prs = tmp_path / "gh-prs.json"
        self.gh_fail = tmp_path / "gh-fail"
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.gh_prs.write_text("[]\n", encoding="utf-8")
        write_script(
            self.bin / "gh",
            f'echo "$@" >> "{self.gh_calls}"\n'
            f'if [ -e "{self.gh_fail}" ]; then echo "gh says no" >&2; exit 1; fi\n'
            'case "$1 $2" in\n'
            f'  "pr list") cat "{self.gh_prs}" ;;\n'
            '  "repo view") echo owner/repo ;;\n'
            f'  "pr create") echo \'[{{"url": "{_URL}"}}]\' > "{self.gh_prs}"; '
            f'echo "{_URL}" ;;\n'
            "esac\n",
        )
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        self.worktree = self.root / _TREE

    def start(self, *args: str, cwd: Path | None = None) -> Result:
        self.monkeypatch.chdir(cwd or self.root)
        return runner.invoke(app, ["start", "005", *args])

    def gh_creates(self) -> int:
        if not self.gh_calls.exists():
            return 0
        calls = self.gh_calls.read_text(encoding="utf-8").splitlines()
        return sum(call.startswith("pr create") for call in calls)

    def to_worktree_stage(self) -> Result:
        """Run ``start``, doing the pushes it asks for, until it stops asking."""
        self.start()
        git(self.root, "push", "-q", "origin", "main")
        self.start()
        git(self.root, "push", "-qu", "origin", _BRANCH)
        return self.start()

    def first_commit(self) -> None:
        """Commit work on the plan's branch in the worktree, and push it."""
        (self.worktree / "work.txt").write_text("work\n", encoding="utf-8")
        git(self.worktree, "add", "work.txt")
        git(self.worktree, "commit", "-qm", "work")
        git(self.worktree, "push", "-q", "origin", _BRANCH)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_start_runs_to_a_draft_pr_with_a_stop_at_each_push(scene: Scene) -> None:
    first = scene.start()
    assert first.exit_code == 1
    assert "done base: on main, clean, not behind origin/main" in first.output
    assert "ran activate: plan 005 is active" in first.output
    assert "done ignore:" in first.output
    assert "1 are plan 005's own, 0 are other" in first.output
    assert "stopped:" in first.output
    assert "git push origin main" in first.output
    # Nothing was published, and nothing past the stop ran.
    assert git_out(scene.root, "rev-parse", "origin/main") != git_out(
        scene.root, "rev-parse", "main"
    )
    assert git_out(scene.root, "branch", "--list", _BRANCH) == ""

    git(scene.root, "push", "-q", "origin", "main")
    second = scene.start()
    assert second.exit_code == 1
    assert "done activate:" in second.output
    assert "done push-base: main is level with origin/main" in second.output
    assert f"ran branch: created {_BRANCH} from main" in second.output
    assert f"ran worktree: created {_TREE} on {_BRANCH}" in second.output
    assert f"git push -u origin {_BRANCH}" in second.output
    assert git_out(scene.root, "ls-remote", "--heads", "origin", _BRANCH) == ""

    git(scene.root, "push", "-qu", "origin", _BRANCH)
    third = scene.start()
    assert third.exit_code == 0, third.output
    assert f"done branch: {_BRANCH} exists" in third.output
    assert "done worktree:" in third.output
    assert "done setup:" in third.output
    assert f"done push: {_BRANCH} is level with origin/{_BRANCH}" in third.output
    assert "skipped pr:" in third.output and "level with main" in third.output
    assert f"work in {_TREE}" in third.output
    assert scene.gh_creates() == 0

    scene.first_commit()
    fourth = scene.start(cwd=scene.worktree)
    assert fourth.exit_code == 0, fourth.output
    assert f"skipped base: on {_BRANCH}" in fourth.output
    assert "ignore:" not in fourth.output and "push-base:" not in fourth.output
    assert f"ran pr: recorded {_URL}" in fourth.output
    assert f"git push origin {_BRANCH}" in fourth.output
    text = (scene.worktree / _REL_PLAN).read_text(encoding="utf-8")
    assert f"pr: {_URL}" in text
    assert git_out(scene.worktree, "log", "-1", "--format=%s").strip() == (
        "plan [pr]: 005 - my-thing"
    )

    calls = scene.gh_calls.read_text(encoding="utf-8")
    assert "--draft --base main" in calls
    assert f"--head {_BRANCH}" in calls
    assert "--title My thing" in calls
    assert (
        "Implements [.planners/plans/005-my-thing/plan.md]"
        "(https://github.com/owner/repo/blob/main/.planners/plans/005-my-thing/plan.md)"
    ) in calls

    git(scene.worktree, "push", "-q", "origin", _BRANCH)
    last = scene.start(cwd=scene.worktree)
    assert last.exit_code == 0, last.output
    assert f"done pr: the plan records {_URL}" in last.output
    assert scene.gh_creates() == 1
    assert text.count("— Activated.") == 1
    assert text.count("— PR opened:") == 1


def test_start_from_the_main_checkout_reads_the_pr_from_the_branch(
    scene: Scene,
) -> None:
    scene.to_worktree_stage()
    scene.first_commit()
    scene.start(cwd=scene.worktree)
    git(scene.worktree, "push", "-q", "origin", _BRANCH)
    # The base's copy of the plan has no PR: set-pr committed on the branch.
    assert f"pr: {_URL}" not in scene.plan.read_text(encoding="utf-8")
    result = scene.start()
    assert result.exit_code == 0, result.output
    assert f"done pr: the plan records {_URL}" in result.output
    assert scene.gh_creates() == 1


def test_start_stops_on_a_dirty_tree_before_activating(scene: Scene) -> None:
    (scene.root / "scratch.txt").write_text("x\n", encoding="utf-8")
    result = scene.start()
    assert result.exit_code == 1
    assert "1 uncommitted change(s)" in result.output
    assert "scratch.txt" in result.output
    assert "status: draft" in scene.plan.read_text(encoding="utf-8")

    (scene.root / "scratch.txt").unlink()
    assert "ran activate:" in scene.start().output


def test_start_counts_uncommitted_edits_to_a_draft_plan(scene: Scene) -> None:
    with scene.plan.open("a", encoding="utf-8") as handle:
        handle.write("\nAn edit in progress.\n")
    result = scene.start()
    assert result.exit_code == 1
    assert "uncommitted change" in result.output
    assert "status: draft" in scene.plan.read_text(encoding="utf-8")


def test_start_refuses_a_branch_off_the_mainline(scene: Scene) -> None:
    git(scene.root, "checkout", "-qb", "other")
    result = scene.start()
    assert result.exit_code == 1
    assert "HEAD is on other, not a mainline branch" in result.output
    assert "status: draft" in scene.plan.read_text(encoding="utf-8")


def test_start_stops_on_a_base_behind_its_upstream(
    scene: Scene, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", "-b", "main", str(scene.remote), str(other)],
        check=True,
        capture_output=True,
    )
    set_identity(other)
    (other / "theirs.txt").write_text("theirs\n", encoding="utf-8")
    commit_all(other, "theirs")
    git(other, "push", "-q", "origin", "main")

    result = scene.start()
    assert result.exit_code == 1
    assert "main is 1 behind origin/main" in result.output
    assert "git pull --ff-only" in result.output
    assert "status: draft" in scene.plan.read_text(encoding="utf-8")

    git(scene.root, "pull", "-q", "--ff-only")
    assert "ran activate:" in scene.start().output


def test_start_finishes_an_activation_that_failed_to_commit(scene: Scene) -> None:
    hook = scene.root / ".git" / "hooks" / "pre-commit"
    write_script(hook, "exit 1\n")
    failed = scene.start()
    assert failed.exit_code == 1
    assert "status: active" in scene.plan.read_text(encoding="utf-8")
    assert git_out(scene.root, "log", "-1", "--format=%s").strip() == "initial commit"

    hook.unlink()
    resumed = scene.start()
    assert "done base:" in resumed.output
    assert "committing the pending activation" in resumed.output
    assert git_out(scene.root, "log", "-1", "--format=%s").strip() == (
        "plan [activate]: 005 - my-thing"
    )
    assert scene.plan.read_text(encoding="utf-8").count("— Activated.") == 1


def test_start_lists_commits_that_are_not_the_plans_before_the_push(
    scene: Scene,
) -> None:
    (scene.root / "other.txt").write_text("other\n", encoding="utf-8")
    commit_all(scene.root, "unrelated work")
    result = scene.start()
    assert result.exit_code == 1
    assert "1 are plan 005's own, 1 are other" in result.output
    assert "unrelated work" in result.output
    assert "Confirm the commits above" in result.output


def test_start_stops_for_a_base_with_no_upstream(scene: Scene) -> None:
    git(scene.root, "branch", "--unset-upstream")
    result = scene.start()
    assert result.exit_code == 1
    assert "main has no upstream" in result.output
    assert "git push -u origin main" in result.output


def test_start_commits_the_ignore_rule_when_it_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, ignore=False)
    result = scene.start()
    assert "ran ignore: committed .worktrees/ to .gitignore" in result.output
    assert (scene.root / ".gitignore").read_text(encoding="utf-8") == ".worktrees/\n"
    assert git_out(scene.root, "log", "-1", "--format=%s").strip() == (
        "ignore .worktrees"
    )
    # Not the plan's own, so it is listed for the person pushing.
    assert "1 are plan 005's own, 1 are other" in result.output
    assert "done ignore:" in scene.start().output


def test_start_appends_the_ignore_rule_to_a_gitignore_without_a_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, ignore=False)
    (scene.root / ".gitignore").write_text("*.pyc", encoding="utf-8")
    commit_all(scene.root, "ignore bytecode")
    scene.start()
    assert (scene.root / ".gitignore").read_text(encoding="utf-8") == (
        "*.pyc\n.worktrees/\n"
    )


def test_start_reports_a_custom_worktree_path_that_is_not_ignored(
    scene: Scene,
) -> None:
    result = scene.start("--worktree", "elsewhere/tree")
    assert "skipped ignore: elsewhere/tree is not ignored" in result.output
    assert "note: elsewhere/tree is outside .worktrees/" in result.output
    assert ".gitignore" not in git_out(scene.root, "show", "--name-only", "HEAD")


def test_start_uses_the_worktree_the_log_records(scene: Scene) -> None:
    (scene.root / ".gitignore").write_text("trees/\n", encoding="utf-8")
    commit_all(scene.root, "ignore trees")
    git(scene.root, "push", "-q", "origin", "main")
    scene.start("--worktree", "trees/mine")
    git(scene.root, "push", "-q", "origin", "main")
    # A re-run with no flag reads the path back rather than taking the default.
    result = scene.start()
    assert "ran worktree: created trees/mine" in result.output
    assert (scene.root / "trees" / "mine" / _REL_PLAN).exists()


def test_start_stops_when_something_else_holds_the_worktree_path(
    scene: Scene,
) -> None:
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    scene.worktree.mkdir(parents=True)
    result = scene.start()
    assert result.exit_code == 1
    assert f"{_TREE} exists and is not on {_BRANCH}" in result.output
    assert f"ran branch: created {_BRANCH}" in result.output

    scene.worktree.rmdir()
    resumed = scene.start()
    assert f"done branch: {_BRANCH} exists" in resumed.output
    assert f"ran worktree: created {_TREE}" in resumed.output


def test_start_accepts_a_worktree_at_another_path(scene: Scene, tmp_path: Path) -> None:
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    moved = tmp_path / "moved"
    git(scene.root, "branch", _BRANCH, "main")
    git(scene.root, "worktree", "add", "-q", str(moved), _BRANCH)
    result = scene.start()
    assert f"done worktree: {_BRANCH} is checked out at {moved}" in result.output
    assert not scene.worktree.exists()


def test_start_says_to_prune_a_worktree_that_is_gone(scene: Scene) -> None:
    scene.to_worktree_stage()
    # Registered and gone: what a hand-deleted directory leaves behind.
    shutil.rmtree(scene.worktree)
    result = scene.start()
    assert result.exit_code == 1
    assert "git worktree prune" in result.output


def test_start_follows_a_branch_that_is_only_on_the_remote(scene: Scene) -> None:
    scene.to_worktree_stage()
    git(scene.root, "worktree", "remove", "--force", str(scene.worktree))
    git(scene.root, "branch", "-qD", _BRANCH)
    result = scene.start()
    assert f"ran branch: created {_BRANCH} from origin/{_BRANCH}" in result.output
    assert result.exit_code == 0, result.output
    assert (
        git_out(
            scene.root, "rev-parse", "--abbrev-ref", f"{_BRANCH}@{{upstream}}"
        ).strip()
        == f"origin/{_BRANCH}"
    )


def test_start_no_worktree_switches_the_main_checkout(scene: Scene) -> None:
    scene.start("--no-worktree")
    assert "none (main checkout)" in scene.plan.read_text(encoding="utf-8")
    git(scene.root, "push", "-q", "origin", "main")
    second = scene.start()
    assert "skipped ignore: the work is in the main checkout" in second.output
    assert f"ran worktree: switched the checkout to {_BRANCH}" in second.output
    assert "skipped setup: the main checkout is set up already" in second.output
    assert git_out(scene.root, "branch", "--show-current").strip() == _BRANCH
    assert not scene.worktree.exists()
    # Now on the plan's branch, so the re-run skips what belongs on the mainline.
    git(scene.root, "push", "-qu", "origin", _BRANCH)
    third = scene.start()
    assert third.exit_code == 0, third.output
    assert f"skipped base: on {_BRANCH}" in third.output


def test_setup_runs_the_repos_hook_once(scene: Scene) -> None:
    runs_file = scene.root.parent / "hook-runs"
    hooks = scene.root / ".planners" / "hooks"
    hooks.mkdir()
    write_script(
        hooks / "post-worktree",
        f'pwd >> "{runs_file}"\nexit 0\n',
    )
    commit_all(scene.root, "add hook")
    git(scene.root, "push", "-q", "origin", "main")
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    second = scene.start()
    assert "ran setup: ran the post-worktree hook" in second.output
    assert "done setup:" in scene.start().output
    runs = runs_file.read_text(encoding="utf-8").splitlines()
    assert [Path(run).resolve() for run in runs] == [scene.worktree.resolve()]
    # The marker lives under the worktree's git directory, not in its tree.
    assert git_out(scene.worktree, "status", "--porcelain") == ""


def test_setup_reruns_after_a_failing_hook(scene: Scene) -> None:
    flag = scene.root.parent / "hook-ok"
    hooks = scene.root / ".planners" / "hooks"
    hooks.mkdir()
    write_script(
        hooks / "post-worktree",
        f'[ -e "{flag}" ] && exit 0\necho "hook says no" >&2\nexit 3\n',
    )
    commit_all(scene.root, "add hook")
    git(scene.root, "push", "-q", "origin", "main")
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    failed = scene.start()
    assert failed.exit_code == 1
    assert "hook says no" in failed.output

    flag.touch()
    assert "ran setup: ran the post-worktree hook" in scene.start().output


def test_setup_syncs_and_copies_claude_and_reports_the_rest(
    scene: Scene, tmp_path: Path
) -> None:
    write_script(
        scene.bin / "uv", f'echo "$@" >> "{tmp_path}/uv-calls"\ntouch uv-ran\nexit 0\n'
    )
    (scene.root / "uv.lock").write_text("", encoding="utf-8")
    (scene.root / ".gitignore").write_text(
        ".worktrees/\n.claude/\ndata\nuv-ran\n", encoding="utf-8"
    )
    (scene.root / "pyproject.toml").write_text(
        '[tool.uv.sources]\nnear = { path = "../near" }\n'
        'pinned = { git = "https://example.com/pinned" }\n',
        encoding="utf-8",
    )
    commit_all(scene.root, "project files")
    git(scene.root, "push", "-q", "origin", "main")
    (scene.root / ".claude").mkdir()
    (scene.root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    (scene.root / "data").symlink_to(tmp_path)

    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    result = scene.start()
    assert "ran setup: copied .claude/, ran uv sync" in result.output
    assert "note: near is a relative path dependency" in result.output
    assert "pinned" not in result.output
    assert "note: data is a symlink in the main checkout" in result.output
    assert (scene.worktree / ".claude" / "settings.json").exists()
    assert (scene.worktree / "uv-ran").exists()
    assert (tmp_path / "uv-calls").read_text(encoding="utf-8") == "sync\n"


def test_setup_says_when_it_knows_no_environment(scene: Scene) -> None:
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    result = scene.start()
    assert "skipped setup: nothing this step knows how to set up" in result.output
    assert "note: no uv.lock and no .planners/hooks/post-worktree" in result.output


def test_setup_reruns_after_a_failed_sync(scene: Scene, tmp_path: Path) -> None:
    flag = tmp_path / "uv-ok"
    write_script(
        scene.bin / "uv",
        f'[ -e "{flag}" ] && exit 0\necho "cannot sync" >&2\nexit 2\n',
    )
    (scene.root / "uv.lock").write_text("", encoding="utf-8")
    commit_all(scene.root, "lock")
    git(scene.root, "push", "-q", "origin", "main")
    scene.start()
    git(scene.root, "push", "-q", "origin", "main")
    failed = scene.start()
    assert failed.exit_code == 1
    assert "cannot sync" in failed.output

    flag.touch()
    assert "ran setup: ran uv sync" in scene.start().output


def test_start_asks_for_a_push_of_commits_on_the_branch(scene: Scene) -> None:
    scene.to_worktree_stage()
    (scene.worktree / "work.txt").write_text("work\n", encoding="utf-8")
    git(scene.worktree, "add", "work.txt")
    git(scene.worktree, "commit", "-qm", "work")
    result = scene.start(cwd=scene.worktree)
    assert result.exit_code == 1
    assert f"{_BRANCH} has 1 commit(s) not on origin/{_BRANCH}" in result.output
    assert f"git push origin {_BRANCH}" in result.output
    assert scene.gh_creates() == 0


def test_start_retries_a_pr_gh_refused(scene: Scene) -> None:
    scene.to_worktree_stage()
    scene.first_commit()
    scene.gh_fail.touch()
    failed = scene.start(cwd=scene.worktree)
    assert failed.exit_code == 1
    assert "gh says no" in failed.output

    scene.gh_fail.unlink()
    assert f"ran pr: recorded {_URL}" in scene.start(cwd=scene.worktree).output
    assert scene.gh_creates() == 1


def test_start_adopts_an_open_pr_the_plan_does_not_record(scene: Scene) -> None:
    scene.to_worktree_stage()
    scene.first_commit()
    scene.gh_prs.write_text(f'[{{"url": "{_URL}"}}]\n', encoding="utf-8")
    result = scene.start(cwd=scene.worktree)
    assert f"ran pr: recorded {_URL}" in result.output
    assert scene.gh_creates() == 0
    text = (scene.worktree / _REL_PLAN).read_text(encoding="utf-8")
    assert f"pr: {_URL}" in text


def test_start_with_no_remote_runs_in_one_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, kind=None)
    result = scene.start()
    assert result.exit_code == 0, result.output
    assert "skipped push-base: no remote to push to" in result.output
    assert "skipped push: no remote to push to" in result.output
    assert "skipped pr: origin is none" in result.output
    assert scene.worktree.exists()
    assert scene.gh_creates() == 0


def test_start_on_a_single_branch_remote_pushes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, kind="single-branch")
    result = scene.start()
    assert result.exit_code == 0, result.output
    assert "skipped push-base: origin is single-branch: 1 commit(s)" in result.output
    assert "skipped push: origin is single-branch" in result.output
    assert "skipped pr: origin is single-branch" in result.output
    assert git_out(scene.root, "ls-remote", "--heads", "origin", _BRANCH) == ""


def test_start_on_a_bare_remote_asks_for_the_pushes_and_opens_no_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, kind="bare")
    result = scene.to_worktree_stage()
    assert result.exit_code == 0, result.output
    assert "skipped pr: origin is bare" in result.output
    assert scene.gh_creates() == 0


@pytest.mark.parametrize("status", ["done", "retired", "implemented"])
def test_start_refuses_a_plan_past_starting(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene(tmp_path, monkeypatch, status=status)
    result = scene.start()
    assert result.exit_code == 1
    assert f"plan 005 is {status}; there is nothing to start" in result.output


def test_start_refuses_a_recorded_mainline_branch(scene: Scene) -> None:
    text = scene.plan.read_text(encoding="utf-8")
    scene.plan.write_text(text.replace("branch:\n", "branch: main\n"), encoding="utf-8")
    commit_all(scene.root, "record main")
    result = scene.start()
    assert result.exit_code == 1
    assert "records the mainline branch main" in result.output


def test_start_refuses_a_nested_subplan(scene: Scene) -> None:
    subplans = scene.plan.parent / "subplans"
    subplans.mkdir()
    (subplans / "a-step.md").write_text(
        "---\nstatus: draft\nbranch:\n---\n\n# A step\n", encoding="utf-8"
    )
    scene.monkeypatch.chdir(scene.root)
    result = runner.invoke(app, ["start", "005a"])
    assert result.exit_code == 1
    assert "nested subplan" in result.output


def test_start_stops_when_it_cannot_read_the_plan(scene: Scene) -> None:
    scene.plan.write_text("not a plan\n", encoding="utf-8")
    result = scene.start()
    assert result.exit_code == 1
    assert "cannot read" in result.output
