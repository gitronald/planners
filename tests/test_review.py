"""Tests for ``planners review``: the evidence module and the CLI command."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners import review as review_mod
from planners.cli import app
from planners.metadata import Status
from planners.review import (
    extract_code_refs,
    extract_plan_refs,
    gather,
    last_review,
)
from tests.helpers import git_out, init_git

runner = CliRunner()

NOW = "2026-04-30T09:00:00-07:00"


def _plan(
    number: int,
    slug: str,
    status: str,
    created: str,
    body: str = "",
    *,
    branch: str = "",
    concluded: str = "",
    pr: str = "",
) -> str:
    return (
        f"---\nid: {number}\nslug: {slug}\nstatus: {status}\nbranch:{branch}\n"
        f"created: {created}\nconcluded:{concluded}\npr:{pr}\n---\n\n"
        f"# Title of {slug}\n\n## Plan\n\n{body}\n\n## Log\n"
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str, date: str) -> None:
    """Commit everything with both the authored and committer dates fixed.

    ``git log --since`` reads the committer date, so a fixture that set only the
    authored one would put every commit at the moment the test ran.
    """
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True, env=env)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


DRAFT_BODY = (
    "Builds on `src/app.py` and `app.run`, replaces `src/gone.py`, and calls "
    "`app.missing`, on `feature/other` from `src/old/`. Pass `--json`; "
    "`meta.status` is not a path. Follows plan 000 "
    "and plan 099.\n\n```bash\ncat `src/fenced.py`\n```"
)
DONE_CREATED = "2026-01-10T10:00:00-08:00"
DRAFT_CREATED = "2026-03-01T10:00:00-08:00"
ACTIVE_CREATED = "2026-03-05T10:00:00-08:00"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on ``main`` with one plan per status and dated history.

    History, oldest first: the initial commit; plan 000 closed; plans 001, 003,
    and 004 added; plan 002 added; a code change; a version bump tagged v0.1.1;
    a commit touching only plan 001; a docs change. ``feature/active-work`` adds
    one commit and is checked out in a dirty worktree.
    """
    root = tmp_path / "repo"
    root.mkdir()
    init_git(root)
    plans = ".planners/plans"

    _write(root, "src/app.py", "def run():\n    return 1\n")
    _write(root, "docs/notes.md", "notes\n")
    _write(
        root,
        f"{plans}/000-old-done/plan.md",
        _plan(0, "old-done", "draft", DONE_CREATED),
    )
    _commit(root, "initial commit", "2026-01-10T10:00:00-08:00")

    _write(
        root,
        f"{plans}/000-old-done/plan.md",
        _plan(
            0,
            "old-done",
            "done",
            DONE_CREATED,
            "Shipped `src/app.py`.",
            branch=" null",
            concluded=" 2026-02-01T10:00:00-08:00",
            pr=" null",
        )
        + "\n- **2026-03-11T09:00:00-08:00** — Review: accounted for. Checked.\n",
    )
    _commit(root, "close plan 000", "2026-02-01T10:00:00-08:00")

    _write(
        root,
        f"{plans}/001-draft-idea/plan.md",
        _plan(1, "draft-idea", "draft", DRAFT_CREATED, DRAFT_BODY),
    )
    _write(
        root,
        f"{plans}/003-umbrella/plan.md",
        _plan(3, "umbrella", "draft", DRAFT_CREATED, "Steps."),
    )
    _write(
        root,
        f"{plans}/003-umbrella/subplans/b-step.md",
        "---\nstatus: draft\nbranch:\n---\n\n# Step\n",
    )
    _write(
        root,
        f"{plans}/003-umbrella/subplans/c-other.md",
        "---\nstatus: done\nbranch:\n---\n\n# Other\n",
    )
    _write(
        root,
        f"{plans}/004-waiting/plan.md",
        _plan(4, "waiting", "blocked", DRAFT_CREATED, "Waits on a decision."),
    )
    _commit(root, "plan [add]: 001 - draft-idea", "2026-03-01T10:00:00-08:00")

    _write(
        root,
        f"{plans}/002-active-work/plan.md",
        _plan(
            2,
            "active-work",
            "active",
            ACTIVE_CREATED,
            "Adds `src/new.py`.",
            branch=" feature/active-work",
        ),
    )
    _commit(root, "plan [add]: 002 - active-work", "2026-03-05T10:00:00-08:00")

    _write(root, "src/app.py", "def run():\n    return 2\n")
    _commit(root, "update app", "2026-03-10T10:00:00-08:00")

    _write(root, "pyproject.toml", "[project]\nversion = '0.1.1'\n")
    _commit(root, "version [patch]: 0.1.1", "2026-03-12T10:00:00-08:00")
    _git(root, "tag", "v0.1.1")

    path = root / plans / "001-draft-idea" / "plan.md"
    path.write_text(path.read_text() + "- **2026-03-15T10:00:00-08:00** — Note.\n")
    _commit(root, "log plan 001", "2026-03-15T10:00:00-08:00")

    _write(root, "docs/notes.md", "more notes\n")
    _commit(root, "touch docs", "2026-03-18T10:00:00-08:00")

    _git(root, "checkout", "-q", "-b", "feature/active-work")
    _write(root, "src/new.py", "def build():\n    pass\n")
    _commit(root, "work on active", "2026-03-21T10:00:00-08:00")
    _git(root, "checkout", "-q", "main")
    worktree = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", str(worktree), "feature/active-work")
    (worktree / "scratch.txt").write_text("in progress\n")
    return root


def _gather(root: Path, **kwargs: object) -> review_mod.Report:
    options: dict = {"now": NOW, "mainline": "main", "gh": False, **kwargs}
    return gather(root, root / ".planners" / "plans", **options)


def _by_prefix(report: review_mod.Report) -> dict[str, review_mod.PlanEvidence]:
    return {item.prefix: item for item in report.plans}


# --------------------------------------------------------------------------
# Pure helpers.


def test_last_review_takes_the_newest_marker_by_instant() -> None:
    body = (
        "## Plan\n\n- **2026-09-01T00:00:00-07:00** — Review: moot. Not the Log.\n\n"
        "## Log\n\n"
        "- **2026-03-02T00:00:00-08:00** — Review: still open. First.\n"
        "- **2026-03-01T00:00:00-08:00** — Review: narrowed. Out of order.\n"
        "- **2026-04-01T00:00:00-07:00** — A plain entry.\n"
    )
    assert last_review(body) == "2026-03-02T00:00:00-08:00"
    assert last_review("## Log\n\n- **2026-03-02T00:00:00-08:00** — Logged.\n") is None
    assert last_review("# Title\n") is None


def test_extract_code_refs_keeps_paths_and_dotted_symbols_only() -> None:
    assert extract_code_refs(DRAFT_BODY) == [
        ("path", "src/app.py"),
        ("symbol", "app.run"),
        ("path", "src/gone.py"),
        ("symbol", "app.missing"),
        ("path", "feature/other"),
        ("path", "src/old/"),
        ("symbol", "meta.status"),
    ]


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        ("planners/cli.py:120", [("path", "planners/cli.py")]),
        ("planners/base.py::_git_out", [("path", "planners/base.py")]),
        ("cli.py", [("path", "cli.py")]),
        ("docs/", [("path", "docs/")]),
        ("./src/app.py", [("path", "src/app.py")]),
        ("planners.base.detect()", [("symbol", "planners.base.detect")]),
        (".planners/plans/{NNN}-*/plan.md", []),
        ("git log --since=<created> -- <path>", []),
        ("https://github.com/owner/repo", []),
        ("/home/someone/file.py", []),
        ("../lib", []),
        ("review", []),
    ],
)
def test_classify_spans(span: str, expected: list[tuple[str, str]]) -> None:
    assert extract_code_refs(f"See `{span}`.") == expected


def test_extract_code_refs_reads_a_span_that_wraps_a_line() -> None:
    assert extract_code_refs("The `src/\napp.py` file.") == []
    assert extract_code_refs("The `planners\n.cli` thing.") == []
    assert extract_code_refs("Run `src/app.py`\nand `src/app.py` again.") == [
        ("path", "src/app.py")
    ]


def test_extract_plan_refs_skips_itself_and_fences() -> None:
    body = "Follows plan 004, plans 007, and plan 012d.\n```\nplan 009\n```\nplan 011"
    assert extract_plan_refs(body, "011") == ["004", "007", "012d"]


# --------------------------------------------------------------------------
# Gathering.


def test_default_selection_is_the_open_statuses(repo: Path) -> None:
    report = _gather(repo)
    assert report.selected == ["002", "004", "001", "003"]
    assert [item.status for item in report.plans] == [
        "active",
        "blocked",
        "draft",
        "draft",
    ]


def test_status_selection_and_single_plan(repo: Path) -> None:
    assert _gather(repo, statuses=(Status.done,)).selected == ["000"]
    assert _gather(repo, statuses=tuple(Status)).selected == [
        "002",
        "004",
        "001",
        "003",
        "000",
    ]
    assert _gather(repo, only="000").selected == ["000"]


def test_summary_counts_and_dates(repo: Path) -> None:
    rows = {row.status: row for row in _gather(repo).summary}
    assert list(rows) == ["active", "blocked", "draft", "done", "total"]
    assert rows["draft"].plans == 2
    assert rows["draft"].commits == 2  # the 001 add and the 001-only log commit
    assert rows["draft"].creation_date == "2026-03-01"
    assert rows["draft"].closed_date is None
    assert rows["draft"].last_date == "2026-03-15"
    assert rows["done"].commits == 2
    assert rows["done"].closed_date == "2026-02-01"
    assert rows["done"].last_date == "2026-02-01"
    assert rows["total"].plans == 5
    assert rows["total"].creation_date == "2026-01-10"
    assert rows["total"].closed_date == "2026-02-01"
    assert rows["total"].last_date == "2026-03-15"


def test_summary_matches_an_independent_rebuild(repo: Path) -> None:
    """Rebuild every row from `git log` and the frontmatter alone."""
    plans_dir = repo / ".planners" / "plans"
    groups: dict[str, list[Path]] = {}
    meta: dict[Path, dict[str, str]] = {}
    for plan in sorted(plans_dir.glob("*/plan.md")):
        fields = dict(
            line.split(":", 1)
            for line in plan.read_text().split("---")[1].strip().splitlines()
        )
        fields = {k.strip(): v.strip() for k, v in fields.items()}
        meta[plan.parent] = fields
        groups.setdefault(fields["status"], []).append(plan.parent)

    def rebuild(status: str, dirs: list[Path]) -> tuple:
        rels = [d.relative_to(repo).as_posix() for d in dirs]
        out = git_out(repo, "log", "--no-merges", "--format=%H %aI", "--", *rels)
        lines = [line.split() for line in out.splitlines()]
        concluded = [
            meta[d]["concluded"]
            for d in dirs
            if meta[d]["concluded"] not in ("", "null")
        ]
        return (
            status,
            len(dirs),
            len({sha for sha, _ in lines}),
            min(meta[d]["created"] for d in dirs)[:10],
            max(concluded)[:10] if concluded else None,
            max(date for _, date in lines)[:10],
        )

    order = ["active", "blocked", "draft", "done", "inactive", "retired"]
    expected = [rebuild(s, groups[s]) for s in order if s in groups]
    expected.append(rebuild("total", [d for s in order for d in groups.get(s, [])]))
    actual = [
        (r.status, r.plans, r.commits, r.creation_date, r.closed_date, r.last_date)
        for r in _gather(repo).summary
    ]
    assert actual == expected


def test_open_subplans_note(repo: Path) -> None:
    report = _gather(repo)
    assert [(o.plan, o.open, o.total) for o in report.open_subplans] == [("003", 1, 2)]
    assert "003: 1 of 2 subplans open" in review_mod.render_text(report)
    umbrella = _by_prefix(report)["003"]
    assert umbrella.subplans == [
        {"letter": "b", "status": "draft", "file": "b-step.md"},
        {"letter": "c", "status": "done", "file": "c-other.md"},
    ]


def test_commits_since_skip_tool_and_plan_only_commits(repo: Path) -> None:
    draft = _by_prefix(_gather(repo))["001"]
    assert draft.window_start == DRAFT_CREATED
    assert draft.last_reviewed is None
    assert draft.commits is not None
    assert [c.subject for c in draft.commits] == ["touch docs", "update app"]
    assert [t.name for t in draft.tags] == ["v0.1.1"]


def test_a_review_marker_starts_the_window(repo: Path) -> None:
    done = _by_prefix(_gather(repo, statuses=(Status.done,)))["000"]
    assert done.last_reviewed == "2026-03-11T09:00:00-08:00"
    assert done.window_start == done.last_reviewed
    assert done.commits is not None
    assert [c.subject for c in done.commits] == ["touch docs"]
    assert [t.name for t in done.tags] == ["v0.1.1"]


def test_code_refs_are_checked_against_the_tree(repo: Path) -> None:
    refs = {r.ref: r for r in _by_prefix(_gather(repo))["001"].code_refs}
    assert refs["src/app.py"].state == "present"
    assert refs["src/app.py"].changed is not None
    assert len(refs["src/app.py"].changed) == 1
    assert refs["src/gone.py"].state == "missing"
    assert refs["app.run"].state == "present"
    assert refs["app.run"].path == "src/app.py"
    assert refs["app.missing"].state == "missing"
    assert "no `missing`" in refs["app.missing"].detail
    assert refs["meta.status"].state == "unresolved"
    assert refs["feature/other"].state == "unresolved"
    assert "branch" in refs["feature/other"].detail
    assert refs["src/old/"].state == "missing"


def test_an_untracked_path_on_disk_is_present(repo: Path) -> None:
    (repo / "src" / "gone.py").write_text("untracked\n")
    refs = {r.ref: r for r in _by_prefix(_gather(repo))["001"].code_refs}
    assert refs["src/gone.py"].state == "present"
    assert refs["src/gone.py"].detail == "untracked"
    assert "src/fenced.py" not in refs


def test_an_untracked_path_outside_the_tree_is_present_not_a_name(
    repo: Path,
) -> None:
    path = repo / ".planners/plans/001-draft-idea/plan.md"
    path.write_text(
        path.read_text().replace("Builds on", "Reads `newpkg/data`, builds on")
    )
    (repo / "newpkg").mkdir()
    (repo / "newpkg" / "data").write_text("untracked\n")
    refs = {r.ref: r for r in _by_prefix(_gather(repo))["001"].code_refs}
    assert refs["newpkg/data"].state == "present"
    assert refs["newpkg/data"].detail == "untracked"


def test_a_symbol_is_found_in_any_same_named_module(repo: Path) -> None:
    _write(repo, "a/util.py", "def other():\n    pass\n")
    _write(repo, "b/util.py", "def helper():\n    pass\n")
    path = repo / ".planners/plans/001-draft-idea/plan.md"
    path.write_text(
        path.read_text().replace("Builds on", "Uses `util.helper`, builds on")
    )
    _commit(repo, "add utils", "2026-03-19T10:00:00-08:00")
    refs = {r.ref: r for r in _by_prefix(_gather(repo))["001"].code_refs}
    assert refs["util.helper"].state == "present"
    assert refs["util.helper"].path == "b/util.py"


def test_a_plan_that_fails_to_parse_is_reported_as_skipped(repo: Path) -> None:
    _write(
        repo,
        ".planners/plans/005-broken/plan.md",
        _plan(5, "broken", "nonsense", DRAFT_CREATED),
    )
    report = _gather(repo)
    assert [note.split(":")[0] for note in report.skipped] == [
        ".planners/plans/005-broken/plan.md"
    ]
    assert "warning: skipped .planners/plans/005-broken/plan.md" in (
        review_mod.render_text(report)
    )


def test_plan_refs_carry_status(repo: Path) -> None:
    draft = _by_prefix(_gather(repo))["001"]
    assert [(r.ref, r.status) for r in draft.plan_refs] == [
        ("000", "done"),
        ("099", None),
    ]
    assert "names plan 099, which does not exist" in draft.flags


def test_active_plan_is_judged_from_its_branch(repo: Path, tmp_path: Path) -> None:
    active = _by_prefix(_gather(repo))["002"]
    assert active.evidence_rev == "feature/active-work"
    assert {r.ref: r.state for r in active.code_refs} == {"src/new.py": "present"}
    state = active.branch_state
    assert state is not None
    assert state.local is True
    assert state.remote is None  # no origin remote
    assert state.ahead == 1
    assert state.last_commit == "2026-03-21T10:00:00-08:00"
    assert state.worktree == str(tmp_path / "wt")
    assert state.dirty is True
    assert any("uncommitted changes" in flag for flag in active.flags)


def test_active_plan_window_includes_its_branch_commits(repo: Path) -> None:
    report = _by_prefix(_gather(repo))
    assert "work on active" in [c.subject for c in report["002"].commits or []]
    assert "work on active" not in [c.subject for c in report["001"].commits or []]


def test_stale_days_sets_the_idle_flag(repo: Path) -> None:
    flagged = _by_prefix(_gather(repo))["002"].flags
    assert any(flag.startswith("no commits for 39 days") for flag in flagged)
    quiet = _by_prefix(_gather(repo, stale_days=60))["002"].flags
    assert not any(flag.startswith("no commits for") for flag in quiet)


def test_blocked_plan_with_no_branch_is_flagged(repo: Path) -> None:
    blocked = _by_prefix(_gather(repo))["004"]
    assert blocked.branch_state is None
    assert blocked.flags == ["blocked plan with no branch recorded"]


def test_missing_branch_is_flagged(repo: Path) -> None:
    path = repo / ".planners/plans/002-active-work/plan.md"
    path.write_text(path.read_text().replace("feature/active-work", "feature/gone"))
    active = _by_prefix(_gather(repo))["002"]
    assert active.evidence_rev == "main"
    assert "branch feature/gone does not exist locally" in active.flags


def test_shallow_clone_downgrades_history(repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(clone)],
        check=True,
    )
    report = gather(clone, clone / ".planners" / "plans", now=NOW, gh=False)
    assert report.shallow is True
    assert all(row.commits is None for row in report.summary)
    draft = _by_prefix(report)["001"]
    assert draft.commits is None
    present = next(r for r in draft.code_refs if r.ref == "src/app.py")
    assert present.state == "present" and present.changed is None
    assert "commits since: unknown" in review_mod.render_text(report)


def test_legacy_layout_is_refused(tmp_path: Path) -> None:
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    with pytest.raises(review_mod.ReviewError, match="legacy"):
        gather(tmp_path, tmp_path / ".planners" / "plans", now=NOW, gh=False)


# --------------------------------------------------------------------------
# CLI.


@pytest.fixture
def cli_repo(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli_mod, "_now", lambda: NOW)
    monkeypatch.setattr(review_mod, "_gh_available", lambda: False)
    return repo


def test_cli_json_report(cli_repo: Path) -> None:
    result = runner.invoke(app, ["review", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["now"] == NOW
    assert data["mainline"] == "main"
    assert data["selected"] == ["002", "004", "001", "003"]
    assert data["summary"][-1]["status"] == "total"
    assert data["summary"][2]["closed_date"] is None
    first = data["plans"][0]
    assert first["prefix"] == "002"
    assert first["branch_state"]["dirty"] is True


def test_cli_text_report(cli_repo: Path) -> None:
    result = runner.invoke(app, ["review", "-s", "done"])
    assert result.exit_code == 0, result.output
    assert "| status | plans | commits |" in result.output
    assert "## 000 Title of old-done (done)" in result.output
    assert "last reviewed: 2026-03-11T09:00:00-08:00" in result.output


def test_cli_single_plan_ignores_status(cli_repo: Path) -> None:
    result = runner.invoke(app, ["review", "0", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected"] == ["000"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["review", "-s", "all", "-s", "draft"], "cannot be combined"),
        (["review", "-s", "open"], "invalid --status"),
        (["review", "001", "-s", "draft"], "not both"),
        (["review", "077"], "no plan 077 found"),
        (["review", "--commit", "-s", "draft"], "--commit takes no plan"),
        (["review", "--allow-branch"], "--commit only"),
    ],
)
def test_cli_rejects_bad_arguments(
    cli_repo: Path, args: list[str], message: str
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert message in result.output


def test_cli_refuses_the_legacy_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "TODO.md").write_text("- [ ] thing\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 1
    assert "legacy" in result.output


def _append_log(repo: Path, rel: str, entry: str) -> None:
    path = repo / rel
    path.write_text(path.read_text() + entry)


DRAFT = ".planners/plans/001-draft-idea/plan.md"
DONE = ".planners/plans/000-old-done/plan.md"
ACTIVE = ".planners/plans/002-active-work/plan.md"
ENTRY = f"- **{NOW}** — Review: still open. Nothing changed.\n"


def test_cli_commit_carries_log_entries_only(cli_repo: Path) -> None:
    _append_log(cli_repo, DRAFT, ENTRY)
    _append_log(cli_repo, DONE, ENTRY)
    (cli_repo / "src" / "app.py").write_text("unrelated edit\n")
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 0, result.output
    assert git_out(cli_repo, "log", "-1", "--format=%s").strip() == (
        "plan [review]: 2 plans"
    )
    changed = git_out(cli_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [".planners/README.md", DONE, DRAFT]
    assert git_out(cli_repo, "status", "--porcelain", "--", ".planners") == ""
    assert "src/app.py" in git_out(cli_repo, "status", "--porcelain")


def test_cli_commit_leaves_other_staged_files_out(cli_repo: Path) -> None:
    _append_log(cli_repo, DRAFT, ENTRY)
    (cli_repo / "src" / "app.py").write_text("staged elsewhere\n")
    _git(cli_repo, "add", "src/app.py")
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 0, result.output
    changed = git_out(cli_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [".planners/README.md", DRAFT]
    assert "M  src/app.py" in git_out(cli_repo, "status", "--porcelain")


def test_cli_commit_accepts_a_new_log_section(cli_repo: Path) -> None:
    path = cli_repo / DONE
    text = path.read_text()
    path.write_text(text[: text.index("## Log")].rstrip("\n") + "\n")
    _commit(cli_repo, "drop the log", "2026-03-19T10:00:00-08:00")
    path.write_text(path.read_text() + "\n## Log\n\n" + ENTRY)
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 0, result.output
    assert git_out(cli_repo, "log", "-1", "--format=%s").strip() == (
        "plan [review]: 1 plan"
    )


def test_cli_commit_refuses_an_active_plan(cli_repo: Path) -> None:
    _append_log(cli_repo, DRAFT, ENTRY)
    _append_log(cli_repo, ACTIVE, ENTRY)
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 1
    assert "plan 002 is active" in result.output
    assert git_out(cli_repo, "log", "-1", "--format=%s").strip() == "touch docs"


def test_cli_commit_refuses_an_edit_outside_the_log(cli_repo: Path) -> None:
    path = cli_repo / DRAFT
    path.write_text(path.read_text().replace("Builds on", "Rests on") + ENTRY)
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 1
    assert "changed outside its Log" in result.output


def test_cli_commit_with_nothing_to_commit(cli_repo: Path) -> None:
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 1
    assert "no plan has a changed Log" in result.output


def test_cli_commit_is_guarded_off_the_mainline(cli_repo: Path) -> None:
    _git(cli_repo, "checkout", "-q", "-b", "elsewhere")
    _append_log(cli_repo, DRAFT, ENTRY)
    result = runner.invoke(app, ["review", "--commit"])
    assert result.exit_code == 1
    assert "not a mainline branch" in result.output
    allowed = runner.invoke(app, ["review", "--commit", "--allow-branch"])
    assert allowed.exit_code == 0, allowed.output


def test_pr_state_passes_the_target_after_end_of_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(root: Path, args: list[str], **_: object):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"state": "OPEN", "url": "u"}', "")

    monkeypatch.setattr(review_mod.proc, "run", fake_run)
    state = review_mod._pr_state(tmp_path, "--web", enabled=True)
    assert state is not None and state.state == "open"
    assert calls[0][-2:] == ["--", "--web"]
