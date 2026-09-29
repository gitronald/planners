"""CLI tests for nested subplans: ``subplans``, ``add --nested``, ``validate``."""

import subprocess
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners.cli import app
from planners.subplans import TABLE_END, TABLE_START
from tests.helpers import commit_all, git_out, init_git

runner = CliRunner()

_UMBRELLA = (
    "---\nid: 12\nslug: big-effort\nstatus: {status}\nbranch: {branch}\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
    "# Big effort\n\n## Plan\n\nThe goal.\n\n## Log\n"
)


def _subplan(status: str = "draft", extra: str = "", title: str = "Step") -> str:
    return f"---\nstatus: {status}\nbranch:\n{extra}---\n\n# {title}\n\n## Log\n"


def _repo(
    root: Path, *, status: str = "active", subplans: dict[str, str] | None = None
) -> Path:
    """Write umbrella 012 under ``root`` with the given subplan files."""
    plan_dir = root / ".planners" / "plans" / "012-big-effort"
    plan_dir.mkdir(parents=True)
    branch = " feature/big-effort" if status == "active" else ""
    text = _UMBRELLA.format(status=status, branch=branch.strip())
    (plan_dir / "plan.md").write_text(text.replace("branch: \n", "branch:\n"))
    for name, body in (subplans or {}).items():
        path = plan_dir / "subplans" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return plan_dir


def test_subplans_on_a_plan_with_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--require-closed"])
    assert result.exit_code == 0, result.output
    assert "plan 012 has no nested subplans" in result.output


def test_subplans_lists_and_fails_without_a_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "b-build.md": _subplan("active", "needs: [a]\n"),
            "notes.md": "free-form, not a subplan\n",
        },
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "12"])
    assert result.exit_code == 1
    assert "012a  done" in result.output
    assert "012b  active" in result.output
    assert "needs: a" in result.output
    assert "order: a -> b" in result.output
    assert "notes.md" not in result.output
    assert "no subplan table" in result.output


def test_subplans_write_creates_the_table_and_then_agrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done", title="Look"),
            "b-build.md": _subplan(),
        },
    )
    monkeypatch.chdir(tmp_path)
    written = runner.invoke(app, ["subplans", "012", "--write"])
    assert written.exit_code == 0, written.output
    assert "updated the subplan table" in written.output
    text = (plan_dir / "plan.md").read_text(encoding="utf-8")
    assert "| [a](subplans/a-look.md) | Look | done |  |" in text
    assert text.index(TABLE_END) < text.index("## Log")

    again = runner.invoke(app, ["subplans", "012", "--write"])
    assert again.exit_code == 0
    assert "updated the subplan table" not in again.output
    assert (plan_dir / "plan.md").read_text(encoding="utf-8") == text


def test_subplans_detects_drift_and_set_repairs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan("draft")})
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["subplans", "012", "--write"]).exit_code == 0

    # A hand edit of the frontmatter alone is the drift the check exists for.
    sub = plan_dir / "subplans" / "b-build.md"
    sub.write_text(_subplan("active"), encoding="utf-8")
    drifted = runner.invoke(app, ["subplans", "012"])
    assert drifted.exit_code == 1
    assert "b: table says 'draft', frontmatter says 'active'" in drifted.output

    fixed = runner.invoke(app, ["subplans", "012", "--set", "b=blocked"])
    assert fixed.exit_code == 0, fixed.output
    assert "set b-build.md to blocked" in fixed.output
    assert "status: blocked" in sub.read_text(encoding="utf-8")
    assert "| blocked |" in (plan_dir / "plan.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("assignment", "message"),
    [
        ("b", "--set takes <letter>=<status>"),
        ("bb=done", "--set takes <letter>=<status>"),
        ("b=finished", "invalid status 'finished'"),
        ("c=done", "no subplan 'c'"),
    ],
)
def test_subplans_set_rejects_a_bad_assignment(
    assignment: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--set", assignment])
    assert result.exit_code == 1
    assert message in result.output
    assert "status: draft" in (plan_dir / "subplans" / "b-build.md").read_text()


def test_subplans_require_closed_lists_the_unfinished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "b-build.md": _subplan("active"),
            "c-wait.md": _subplan("blocked"),
            "d-later.md": _subplan("draft"),
            "e-moved.md": _subplan("retired", "moved_to: 015\n"),
            "f-parked.md": _subplan("inactive"),
        },
    )
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["subplans", "012", "--write"]).exit_code == 0
    result = runner.invoke(app, ["subplans", "012", "--require-closed"])
    assert result.exit_code == 1
    for line in ("b: still active", "c: still blocked", "d: still draft"):
        assert line in result.output
    for letter in ("a", "e", "f"):
        assert f"{letter}: still" not in result.output
    assert "3 problem(s)" in result.output


def test_subplans_reports_unreadable_and_invalid_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "b-build.md": "# no frontmatter\n",
            "c-cycle.md": _subplan("draft", "needs: [d]\n"),
            "d-cycle.md": _subplan("draft", "needs: [c]\nmoved_to: 015\n"),
        },
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--write"])
    assert result.exit_code == 1
    assert "b-build.md: missing YAML frontmatter" in result.output
    assert "cycle among: c, d" in result.output
    assert "d-cycle.md: moved_to is set on a draft subplan" in result.output
    assert "order:" not in result.output


def test_subplans_write_refuses_a_table_without_a_status_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    plan = plan_dir / "plan.md"
    plan.write_text(
        plan.read_text()
        + f"\n{TABLE_START}\n| Subplan | Scope |\n|---|---|\n{TABLE_END}\n"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--write"])
    assert result.exit_code == 1
    assert "no Status column" in result.output


def test_activate_points_a_nested_reference_at_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, subplans={"d-step.md": _subplan()})
    monkeypatch.chdir(tmp_path)
    nested = runner.invoke(app, ["activate", "012d", "--no-commit"])
    assert nested.exit_code == 1
    assert "012d is a nested subplan of plan 012" in nested.output
    assert "planners subplans 012 --set d=<status>" in nested.output

    missing = runner.invoke(app, ["activate", "012e", "--no-commit"])
    assert missing.exit_code == 1
    assert "no plan 012e found" in missing.output


def test_add_nested_scaffolds_from_b_and_fills_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(
        app,
        [
            "add",
            "build-it",
            "--parent",
            "12",
            "--nested",
            "--title",
            "Build it",
            "--branch",
            "feature/big-effort-build",
            "--no-commit",
        ],
    )
    assert first.exit_code == 0, first.output
    sub = plan_dir / "subplans" / "b-build-it.md"
    text = sub.read_text(encoding="utf-8")
    assert text.startswith(
        "---\nstatus: draft\nbranch: feature/big-effort-build\n---\n"
    )
    assert "# Build it" in text
    assert "Part of [Big effort](../plan.md)." in text

    second = runner.invoke(
        app, ["add", "review", "--parent", "12", "--nested", "--no-commit"]
    )
    assert second.exit_code == 0, second.output
    assert (plan_dir / "subplans" / "c-review.md").is_file()

    look = runner.invoke(
        app,
        ["add", "look", "--parent", "12", "--nested", "--letter", "a", "--no-commit"],
    )
    assert look.exit_code == 0, look.output
    assert (plan_dir / "subplans" / "a-look.md").is_file()

    umbrella = (plan_dir / "plan.md").read_text(encoding="utf-8")
    assert "| [b](subplans/b-build-it.md) | Build it | draft |  |" in umbrella
    assert "| [a](subplans/a-look.md) |" in umbrella
    # No lettered sibling plan and no index: a nested subplan has neither.
    assert not (tmp_path / ".planners" / "plans" / "012a-look").exists()
    assert not (tmp_path / ".planners" / "README.md").exists()
    assert runner.invoke(app, ["subplans", "012"]).exit_code == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["add", "x", "--nested"], "--nested needs --parent"),
        (["add", "x", "--parent", "12", "--letter", "c"], "--letter applies to"),
        (["add", "x", "--parent", "12", "--nested", "--defer"], "--defer cannot"),
        (["add", "x", "--parent", "12", "--nested", "--letter", "B"], "single letter"),
        (["add", "x", "--parent", "12", "--nested", "--letter", "b"], "already taken"),
        (["add", "x", "--parent", "13", "--nested"], "no umbrella plan 013"),
        (["add", "Bad Slug", "--parent", "12", "--nested"], "unsafe slug"),
    ],
)
def test_add_nested_refusals_write_nothing(
    args: list[str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    before = (plan_dir / "plan.md").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*args, "--no-commit"])
    assert result.exit_code == 1
    assert message in result.output
    assert sorted(p.name for p in (plan_dir / "subplans").iterdir()) == ["b-build.md"]
    assert (plan_dir / "plan.md").read_text(encoding="utf-8") == before


def test_add_nested_refuses_a_closed_or_unreadable_umbrella(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    plan = plan_dir / "plan.md"
    monkeypatch.chdir(tmp_path)

    plan.write_text(
        plan.read_text()
        .replace("status: active", "status: done")
        .replace("concluded:", "concluded: 2026-06-08T12:00:00-07:00")
    )
    closed = runner.invoke(app, ["add", "x", "--parent", "12", "--nested"])
    assert closed.exit_code == 1
    assert "plan 012 is done; it is closed" in closed.output

    plan.write_text(plan.read_text().replace("status: done", "status: bogus"))
    unreadable = runner.invoke(app, ["add", "x", "--parent", "12", "--nested"])
    assert unreadable.exit_code == 1
    assert "invalid status" in unreadable.output
    assert not (plan_dir / "subplans").exists()


def test_add_nested_reports_exhausted_letters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, subplans={"z-last.md": _subplan()})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "x", "--parent", "12", "--nested"])
    assert result.exit_code == 1
    assert "exhausted" in result.output


def test_add_nested_warns_about_an_unreadable_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, subplans={"b-broken.md": "# no frontmatter\n"})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["add", "next", "--parent", "12", "--nested", "--no-commit"]
    )
    assert result.exit_code == 0, result.output
    assert "warning: b-broken.md: missing YAML frontmatter" in result.output


def test_add_nested_commits_on_the_branch_of_an_active_umbrella(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git(tmp_path)
    plan_dir = _repo(tmp_path, status="active")
    commit_all(tmp_path, "initial commit")
    subprocess.run(
        ["git", "checkout", "-qb", "feature/big-effort"], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "build", "--parent", "12", "--nested"])
    assert result.exit_code == 0, result.output
    assert git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [add]: 012b - build"
    )
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/plans/012-big-effort/plan.md",
        ".planners/plans/012-big-effort/subplans/b-build.md",
    ]
    assert git_out(tmp_path, "status", "--porcelain") == ""
    assert (plan_dir / "subplans" / "b-build.md").is_file()


def test_add_nested_guards_the_mainline_for_a_draft_umbrella(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git(tmp_path)
    plan_dir = _repo(tmp_path, status="draft")
    commit_all(tmp_path, "initial commit")
    subprocess.run(["git", "checkout", "-qb", "feature/x"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    refused = runner.invoke(app, ["add", "build", "--parent", "12", "--nested"])
    assert refused.exit_code == 1
    assert "not a mainline branch" in refused.output
    assert not (plan_dir / "subplans").exists()

    allowed = runner.invoke(
        app, ["add", "build", "--parent", "12", "--nested", "--allow-branch"]
    )
    assert allowed.exit_code == 0, allowed.output
    assert "plan [add]: 012b - build" in git_out(tmp_path, "log", "--oneline")


def test_add_parent_without_nested_still_makes_a_lettered_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "step", "--parent", "12", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "012a-step" / "plan.md").is_file()


def test_validate_checks_subplans_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "b-build.md": _subplan("draft", "needs: [x]\n"),
            "c-free.md": "free-form notes with no frontmatter\n",
            "notes.md": "more notes\n",
            "data.csv": "a,b\n",
        },
    )
    monkeypatch.chdir(tmp_path)
    default = runner.invoke(app, ["validate", ".planners/plans"])
    assert default.exit_code == 0, default.output

    strict = runner.invoke(app, ["validate", ".planners/plans", "--subplans"])
    assert strict.exit_code == 1
    assert "c-free.md: missing YAML frontmatter" in strict.output
    assert "notes.md: 'notes.md' is not <letter>-<step>.md" in strict.output
    assert "needs 'x', which has no subplan" in strict.output
    assert "data.csv" not in strict.output
    assert "3 violation(s)" in strict.output


def test_validate_subplans_passes_on_conformant_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "b-build.md": _subplan("blocked", "needs: [a]\n"),
        },
    )
    (tmp_path / ".planners" / "plans" / "013-plain").mkdir()
    (tmp_path / ".planners" / "plans" / "013-plain" / "plan.md").write_text(
        "---\nid: 13\nslug: plain\nstatus: blocked\nbranch:\n"
        "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n# Plain\n"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", ".planners/plans", "--subplans"])
    assert result.exit_code == 0, result.output
    assert "2 file(s) valid" in result.output


_NO_STATUS_TABLE = f"\n{TABLE_START}\n| Step | Scope |\n|---|---|\n{TABLE_END}\n"


def _snapshot(plan_dir: Path) -> dict[str, str]:
    """Every file under a plan directory, by relative path, with its text."""
    return {
        str(path.relative_to(plan_dir)): path.read_text(encoding="utf-8")
        for path in sorted(plan_dir.rglob("*"))
        if path.is_file()
    }


def test_add_nested_writes_nothing_when_the_table_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The subplan file used to be written first, so a table the command may not
    # write left an orphan file with no row and no commit.
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    plan = plan_dir / "plan.md"
    plan.write_text(plan.read_text() + _NO_STATUS_TABLE)
    before = _snapshot(plan_dir)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["add", "next", "--parent", "12", "--nested", "--no-commit"]
    )
    assert result.exit_code == 1
    assert "no Status column" in result.output
    assert "wrote" not in result.output
    assert _snapshot(plan_dir) == before


def test_subplans_set_applies_every_assignment_or_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Assignments used to be written as they were read, so a bad one after a
    # good one left the frontmatter changed and the table not regenerated.
    plan_dir = _repo(
        tmp_path, subplans={"b-build.md": _subplan(), "c-check.md": _subplan()}
    )
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["subplans", "012", "--write"]).exit_code == 0
    before = _snapshot(plan_dir)

    for bad in ("z=done", "c=bogus", "c"):
        result = runner.invoke(
            app, ["subplans", "012", "--set", "b=done", "--set", bad]
        )
        assert result.exit_code == 1, bad
        assert "set b-build.md" not in result.output
        assert _snapshot(plan_dir) == before, bad

    both = runner.invoke(
        app, ["subplans", "012", "--set", "b=done", "--set", "c=active"]
    )
    assert both.exit_code == 0, both.output
    assert "set b-build.md to done" in both.output
    assert "set c-check.md to active" in both.output


def test_subplans_set_writes_nothing_when_the_table_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    plan = plan_dir / "plan.md"
    plan.write_text(plan.read_text() + _NO_STATUS_TABLE)
    before = _snapshot(plan_dir)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--set", "b=done"])
    assert result.exit_code == 1
    assert "no Status column" in result.output
    assert _snapshot(plan_dir) == before


def test_subplans_set_the_same_letter_twice_keeps_the_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["subplans", "012", "--set", "b=active", "--set", "b=done"]
    )
    assert result.exit_code == 0, result.output
    assert "status: done" in (plan_dir / "subplans" / "b-build.md").read_text()
    assert "| done |" in (plan_dir / "plan.md").read_text()


def test_subplans_set_does_not_invent_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file named like a subplan with no frontmatter is somebody's notes. `--set`
    # used to prepend a frontmatter block to it and add it to the table.
    notes = "# Free-form notes\n\nNo frontmatter here.\n"
    plan_dir = _repo(tmp_path, subplans={"b-notes.md": notes})
    before = _snapshot(plan_dir)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--set", "b=done"])
    assert result.exit_code == 1
    assert "has no frontmatter; it is not a subplan" in result.output
    assert _snapshot(plan_dir) == before


def test_subplans_set_repairs_a_status_that_does_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The frontmatter exists, so the status in it can be put right.
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan("waiting")})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--set", "b=blocked"])
    assert result.exit_code == 0, result.output
    assert "status: blocked" in (plan_dir / "subplans" / "b-build.md").read_text()


def test_sync_refuses_a_planned_text_that_is_not_a_subplan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The last line of defense behind the commands: whatever builds the text, one
    # that does not read as a subplan is never written.
    plan_dir = _repo(tmp_path, subplans={"b-build.md": _subplan()})
    before = _snapshot(plan_dir)
    target = plan_dir / "subplans" / "c-next.md"
    with pytest.raises(typer.Exit):
        cli_mod._sync_subplans(
            tmp_path, plan_dir / "plan.md", {target: "# no frontmatter\n"}
        )
    assert _snapshot(plan_dir) == before


def test_subplans_order_leaves_out_a_retired_subplan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The order is of the work to be run. A retired subplan with no needs used to
    # print as a root of the chain: `(a, e) -> b`.
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "b-build.md": _subplan("active", "needs: [a, e]\n"),
            "e-moved.md": _subplan("retired", "moved_to: 015\n"),
        },
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--write"])
    assert result.exit_code == 0, result.output
    assert "order: a -> b" in result.output
    assert "012e  retired" in result.output


def test_subplans_prints_no_order_when_only_a_retired_subplan_has_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        subplans={
            "a-look.md": _subplan("done"),
            "e-moved.md": _subplan("retired", "needs: [a]\n"),
        },
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["subplans", "012", "--write"])
    assert result.exit_code == 0, result.output
    assert "order:" not in result.output
