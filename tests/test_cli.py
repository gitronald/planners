"""End-to-end tests for the CLI commands via Typer's runner."""

import subprocess
from importlib import metadata
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners.cli import app
from planners.metadata import PlanMetadata

runner = CliRunner()


def _write_plan(plans_dir: Path, dirname: str, body: str) -> Path:
    """Write a plan at ``<plans_dir>/<dirname>/plan.md`` and return its path."""
    plan_dir = plans_dir / dirname
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / "plan.md"
    path.write_text(body, encoding="utf-8")
    return path


def _write_file(path: Path, body: str) -> Path:
    """Write an arbitrary (non-plan) file, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


_VALID_PLAN = (
    "---\nid: 1\nslug: thing\nstatus: active\nbranch: feature/thing\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n# Thing\n"
)


def test_schema_lists_fields() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    fields = ("id", "slug", "sub", "status", "branch", "created", "concluded", "pr")
    for field in fields:
        assert field in result.output


def test_schema_list_models() -> None:
    result = runner.invoke(app, ["schema", "--list"])
    assert result.exit_code == 0
    assert "PlanMetadata" in result.output


def test_version_flag_prints_metadata_version() -> None:
    expected = metadata.version("planners")
    for flag in ("--version", "-v"):
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert f"planners {expected}" in result.output


def test_validate_passes_on_conformant_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", ".planners/plans"])
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("dirname", "body"),
    [
        # status not in the enum
        ("001-thing", _VALID_PLAN.replace("status: active", "status: bogus")),
        # legacy abandoned
        ("001-thing", _VALID_PLAN.replace("status: active", "status: abandoned")),
        # literal "none"
        ("001-thing", _VALID_PLAN.replace("pr:", "pr: none")),
        # id/slug disagree with the plan directory name
        ("009-other", _VALID_PLAN),
    ],
)
def test_validate_fails_on_violations(
    dirname: str, body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", dirname, body)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", f".planners/plans/{dirname}/plan.md"])
    assert result.exit_code == 1


def test_validate_named_plan_dir_checks_its_plan_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Naming a plan directory itself (not its plan.md, not the container) must
    # validate the plan.md inside it — not silently report zero files.
    _write_plan(tmp_path / ".planners" / "plans", "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    ok = runner.invoke(app, ["validate", ".planners/plans/001-thing"])
    assert ok.exit_code == 0
    assert "1 file(s) valid" in ok.output

    # and a broken plan named by its dir is flagged, not skipped
    _write_plan(
        tmp_path / ".planners" / "plans",
        "002-bad",
        _VALID_PLAN.replace("status: active", "status: bogus").replace(
            "id: 1", "id: 2"
        ),
    )
    bad = runner.invoke(app, ["validate", ".planners/plans/002-bad"])
    assert bad.exit_code == 1


def test_validate_empty_container_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pointing validate at a directory with no plan dirs (e.g. `.planners`
    # instead of `.planners/plans`) must FAIL — examining zero files is not a
    # vacuous pass. It names the empty directory so the mistaken target is visible.
    (tmp_path / ".planners" / "plans").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", ".planners"])
    assert result.exit_code == 1
    assert "no plans found under" in result.output


def test_validate_repo_root_discovers_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `validate .` from a checkout must discover the plans under .planners/plans —
    # not sweep the root for top-level NNN-slug dirs (there are none) and match zero.
    _write_plan(tmp_path / ".planners" / "plans", "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 0, result.output
    assert "1 file(s) valid" in result.output


def test_validate_zero_files_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A repo whose .planners/plans tree is empty: `validate .` matches zero files
    # and must exit non-zero (the vacuous-pass bug that green-lit unexamined repos).
    (tmp_path / ".planners" / "plans").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 1
    assert "no plan files matched" in result.output or "no plans found" in result.output


def test_validate_allow_empty_downgrades_zero_match_to_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --allow-empty restores warn-and-pass for callers that tolerate an empty set.
    (tmp_path / ".planners" / "plans").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", ".", "--allow-empty"])
    assert result.exit_code == 0, result.output
    assert "0 file(s)" in result.output


def test_add_no_commit_writes_conformant_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["add", "my-feature", "--title", "My Feature", "--no-commit"]
    )
    assert result.exit_code == 0
    path = tmp_path / ".planners" / "plans" / "000-my-feature" / "plan.md"
    assert path.exists()
    meta = PlanMetadata.from_file(path)
    assert meta.id == 0
    assert meta.slug == "my-feature"
    assert meta.title == "My Feature"
    assert meta.validate() == []


def test_add_numbers_increment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_plan(
        tmp_path / ".planners" / "plans",
        "000-first",
        _VALID_PLAN.replace("id: 1", "id: 0").replace("slug: thing", "slug: first"),
    )
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["add", "second", "--no-commit"])
    assert (tmp_path / ".planners" / "plans" / "001-second" / "plan.md").exists()


def test_add_parent_creates_lettered_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plans = tmp_path / ".planners" / "plans"
    # umbrella first (000-umbrella), then two subplans under it
    assert runner.invoke(app, ["add", "umbrella", "--no-commit"]).exit_code == 0
    first = runner.invoke(app, ["add", "step-one", "--parent", "0", "--no-commit"])
    assert first.exit_code == 0, first.output
    path = plans / "000a-step-one" / "plan.md"
    assert path.exists()
    meta = PlanMetadata.from_file(path)
    assert (meta.id, meta.sub) == (0, "a")
    assert meta.validate() == []

    # the next subplan takes the next free letter
    runner.invoke(app, ["add", "step-two", "--parent", "0", "--no-commit"])
    assert (plans / "000b-step-two" / "plan.md").exists()

    # a top-level add is unaffected by subplans: it still gets the next NUMBER
    runner.invoke(app, ["add", "next-top", "--no-commit"])
    assert (plans / "001-next-top" / "plan.md").exists()


def test_add_parent_requires_existing_umbrella(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "orphan", "--parent", "9", "--no-commit"])
    assert result.exit_code == 1
    assert "no umbrella plan 009" in result.output
    # no subplan directory was created for the missing umbrella
    assert not list((tmp_path / ".planners" / "plans").glob("009*"))


def test_add_parent_clean_error_when_letters_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An umbrella whose last subplan is 'z' has no next letter; --parent must
    # exit cleanly with a message, not a raw ord() TypeError traceback.
    monkeypatch.chdir(tmp_path)
    plans = tmp_path / ".planners" / "plans"
    assert runner.invoke(app, ["add", "umbrella", "--no-commit"]).exit_code == 0
    _write_plan(
        plans,
        "000z-last",
        "---\nid: 0\nslug: last\nsub: z\nstatus: active\n"
        "branch: feature/last\ncreated: 2026-06-07T12:00:00-07:00\n"
        "concluded:\npr:\n---\n\n# Last\n",
    )
    result = runner.invoke(app, ["add", "overflow", "--parent", "0", "--no-commit"])
    assert result.exit_code == 1
    assert "exhausted" in result.output
    assert not isinstance(result.exception, TypeError)


def test_add_refuses_existing_plan_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A plan dir already at the next number must not be clobbered.
    (tmp_path / ".planners" / "plans" / "000-my-feature").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "my-feature", "--no-commit"])
    assert result.exit_code == 1
    assert "refusing to overwrite" in result.output


def test_add_rejects_unsafe_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "../evil", "--no-commit"]).exit_code == 1
    # the unsafe slug is rejected before any .planners/ directory is created
    assert not (tmp_path / ".planners").exists()


def test_add_commits_by_default_in_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "feature-x", "--title", "Feature X"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-feature-x" / "plan.md").exists()
    assert (tmp_path / ".planners" / "README.md").exists()
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "plan [add]: 000 - feature-x" in log


def test_index_updates_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["index", "."])
    assert result.exit_code == 0
    readme = (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Plans\n")
    assert "plans/001-thing/plan.md" in readme
    # idempotent: a second run leaves the file byte-identical
    runner.invoke(app, ["index", "."])
    assert (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8") == readme


def test_index_on_empty_repo_writes_empty_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No .planners/plans directory at all: _plan_files returns [] (missing-dir
    # branch) and index writes a title + empty table rather than crashing.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["index", "."])
    assert result.exit_code == 0
    readme = (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Plans\n")
    assert "| # | Plan | Status | Concluded | PR |" in readme


def test_index_rejects_bad_cols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", ".", "--cols", "weird"]).exit_code == 1


def test_validate_directory_ignores_stray_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "001-thing", _VALID_PLAN)
    # stray content that must not be swept into validation:
    _write_file(plans / "notes.md", "scratch\n")  # stray file, not a plan dir
    _write_file(plans / "scratch" / "notes.md", "scratch\n")  # non-plan dir
    _write_file(plans / "002-wip" / "notes.md", "wip\n")  # plan dir, no plan.md
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", ".planners/plans"])
    assert result.exit_code == 0
    assert "1 file(s) valid" in result.output


def test_validate_explicit_non_plan_file_is_still_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The generated index lives at .planners/README.md; naming it (or any
    # non-plan file) directly still validates it, and it fails (no frontmatter).
    _write_file(tmp_path / ".planners" / "README.md", "# Plans\n\nnot a plan\n")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["validate", ".planners/README.md"]).exit_code == 1


def test_index_ignores_stray_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "001-thing", _VALID_PLAN)
    _write_file(plans / "scratch" / "notes.md", "# Notes\n")  # non-plan dir
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["index", "."])
    assert result.exit_code == 0
    readme = (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert "plans/001-thing/plan.md" in readme
    # the stray file is not rendered as a plan row
    assert "[# Notes]" not in readme


def test_add_commit_failure_outside_git_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No git repo here: the commit-by-default path must surface a clean Exit,
    # not a raw CalledProcessError traceback.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "feature-x", "--title", "Feature X"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, subprocess.CalledProcessError)
    # the plan file was still written before the failed commit
    assert (tmp_path / ".planners" / "plans" / "000-feature-x" / "plan.md").exists()


# --- _git: an unusable root is not reported as a missing git ------------------


def test_git_reports_a_vanished_root_rather_than_blaming_git(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing ``root`` must not masquerade as a missing git binary.

    Pinning the commit to ``root`` means ``cwd=root`` can fail on its own, and a
    directory that is not there raises the *same* ``FileNotFoundError`` as a git
    that is not installed. Without the ``is_dir`` split the user is told to
    install a git they already have.
    """
    with pytest.raises(typer.Exit) as exc_info:
        cli_mod._git(tmp_path / "gone", ["status"])

    assert exc_info.value.exit_code == 1
    err = capsys.readouterr().err
    assert "no longer a directory" in err
    assert "git not found on PATH" not in err


def test_git_turns_an_unreadable_root_into_a_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-``FileNotFoundError`` OSError on ``root`` is an error, not a traceback.

    ``chmod 000`` makes ``cwd=root`` raise ``PermissionError``; the docstring
    promises a clear CLI error in every failure mode, so it must not escape.
    """
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    unreadable.chmod(0o000)
    try:
        with pytest.raises(typer.Exit) as exc_info:
            cli_mod._git(unreadable, ["status"])
    finally:
        unreadable.chmod(0o755)

    assert exc_info.value.exit_code == 1
    assert "cannot run git in" in capsys.readouterr().err


def test_git_still_blames_git_when_the_binary_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The original message survives for the case it was written for."""

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(cli_mod.proc, "run", missing)
    with pytest.raises(typer.Exit) as exc_info:
        cli_mod._git(tmp_path, ["status"])

    assert exc_info.value.exit_code == 1
    assert "git not found on PATH" in capsys.readouterr().err


# --- add --defer + finalize: collision-safe batch creation --------------------


def _staged_text(slug: str, created: str, title: str = "", body_extra: str = "") -> str:
    """An unnumbered staged-plan body with a chosen ``created`` (for ordering)."""
    return (
        "---\n"
        "id:\n"
        f"slug: {slug}\n"
        "status: draft\n"
        "branch:\n"
        f"created: {created}\n"
        "concluded:\n"
        "pr:\n"
        "---\n"
        "\n"
        f"# {title or slug}\n"
        f"{body_extra}"
    )


def _write_staged(staging: Path, dirname: str, text: str) -> Path:
    """Write a staged plan at ``<staging>/<dirname>/plan.md`` (direct test control)."""
    d = staging / dirname
    d.mkdir(parents=True, exist_ok=True)
    path = d / "plan.md"
    path.write_text(text, encoding="utf-8")
    return path


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_add_defer_stages_unnumbered_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["add", "my-feature", "--title", "My Feature", "--defer"]
    )
    assert result.exit_code == 0, result.output
    # staged under .planners/staging/<token>-my-feature, no number, no commit
    staged = list((tmp_path / ".planners" / "staging").glob("*-my-feature/plan.md"))
    assert len(staged) == 1
    text = staged[0].read_text(encoding="utf-8")
    assert "\nid:\n" in text  # id left blank for finalize to assign
    assert "slug: my-feature" in text
    assert "# My Feature" in text
    # deferred creation never touches plans/ and never commits
    assert not (tmp_path / ".planners" / "plans").exists()


def test_add_defer_rejects_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add", "x", "--defer", "--parent", "0"])
    assert result.exit_code == 1
    assert "--defer cannot be combined with --parent" in result.output


def test_finalize_orders_by_created_not_dirname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two staged plans whose directory order (alphabetical) is the REVERSE of their
    # created order: finalize must number by created, so the older one gets 000.
    staging = tmp_path / ".planners" / "staging"
    _write_staged(
        staging, "aaaa-newer", _staged_text("newer", "2026-06-11T09:00:00-07:00")
    )
    _write_staged(
        staging, "zzzz-older", _staged_text("older", "2026-06-10T09:00:00-07:00")
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize", "--no-commit"])
    assert result.exit_code == 0, result.output
    plans = tmp_path / ".planners" / "plans"
    assert (plans / "000-older" / "plan.md").exists()
    assert (plans / "001-newer" / "plan.md").exists()
    assert PlanMetadata.from_file(plans / "000-older" / "plan.md").validate() == []
    # staging is drained (the root dir is removed) and the self-check reports OK
    assert not staging.exists()
    assert "self-check OK" in result.output


def test_finalize_assigns_next_numbers_after_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An existing 000 plan means the batch starts at 001.
    _write_plan(
        tmp_path / ".planners" / "plans",
        "000-existing",
        _VALID_PLAN.replace("id: 1", "id: 0").replace("slug: thing", "slug: existing"),
    )
    staging = tmp_path / ".planners" / "staging"
    _write_staged(
        staging, "tok-fresh", _staged_text("fresh", "2026-06-12T09:00:00-07:00")
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "001-fresh" / "plan.md").exists()


def test_finalize_commits_batch_atomically_and_self_check_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path)
    # Distinct created times so the number<->slug mapping is deterministic (the CLI
    # clock has second precision, which would tie two back-to-back `add --defer`s).
    staging = tmp_path / ".planners" / "staging"
    _write_staged(
        staging, "tok-alpha", _staged_text("alpha", "2026-06-10T09:00:00-07:00")
    )
    _write_staged(
        staging, "tok-beta", _staged_text("beta", "2026-06-11T09:00:00-07:00")
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize"])
    assert result.exit_code == 0, result.output
    assert "self-check OK" in result.output
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # the batch lands as ONE commit covering the assigned number range
    assert "plan [add]: 000-001 (2 plans)" in log
    assert log.count("plan [add]") == 1
    # a clean tree is part of the self-check; confirm directly too — scoped to the
    # plan files (the conftest's .gitconfig-empty is an unrelated untracked file).
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert [line for line in porcelain.splitlines() if ".planners" in line] == []


def test_finalize_single_plan_uses_add_slug_commit_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A one-plan batch keeps the familiar `plan [add]: NNN - slug` message.
    _init_git(tmp_path)
    staging = tmp_path / ".planners" / "staging"
    _write_staged(
        staging, "tok-solo", _staged_text("solo", "2026-06-10T09:00:00-07:00")
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize"])
    assert result.exit_code == 0, result.output
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "plan [add]: 000 - solo" in log


def test_finalize_preserves_drafted_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A body the creator drafted into the staged plan survives materialization.
    staging = tmp_path / ".planners" / "staging"
    body = "\n## Plan\n\nDo the thing carefully.\n"
    _write_staged(
        staging,
        "tok-drafted",
        _staged_text("drafted", "2026-06-12T09:00:00-07:00", body_extra=body),
    )
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["finalize", "--no-commit"]).exit_code == 0
    text = (tmp_path / ".planners" / "plans" / "000-drafted" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert "## Plan" in text
    assert "Do the thing carefully." in text


def test_finalize_no_staged_plans_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["finalize"])
    assert result.exit_code == 1
    assert "no staged plans" in result.output


def test_finalize_duplicate_slug_kept_distinct_by_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two concurrent creators picking the same slug: finalize numbers them
    # distinctly (no clobber) and notes the duplicate.
    staging = tmp_path / ".planners" / "staging"
    _write_staged(staging, "tok1-dup", _staged_text("dup", "2026-06-10T09:00:00-07:00"))
    _write_staged(staging, "tok2-dup", _staged_text("dup", "2026-06-11T09:00:00-07:00"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize", "--no-commit"])
    assert result.exit_code == 0, result.output
    plans = tmp_path / ".planners" / "plans"
    assert (plans / "000-dup" / "plan.md").exists()
    assert (plans / "001-dup" / "plan.md").exists()
    assert "duplicate slug" in result.output


def test_finalize_invalid_entry_aborts_before_materializing_any(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A corrupted staged plan (here, an unsafe slug) must abort the whole batch
    # before ANY plan is materialized — validation is hoisted ahead of all
    # filesystem mutation, so a valid earlier plan is never stranded materialized-
    # but-uncommitted. The valid "good" sorts first by created; the bad one second.
    staging = tmp_path / ".planners" / "staging"
    _write_staged(
        staging, "tok-good", _staged_text("good", "2026-06-10T09:00:00-07:00")
    )
    _write_staged(
        staging, "tok-bad", _staged_text("Bad-Slug", "2026-06-11T09:00:00-07:00")
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["finalize", "--no-commit"])
    assert result.exit_code == 1
    assert "unsafe or missing slug" in result.output
    # Nothing materialized: the valid plan was NOT moved out of staging.
    plans = tmp_path / ".planners" / "plans"
    assert list(plans.glob("0*-*")) == []
    # Both staged plans remain intact under staging for the user to fix and re-run.
    assert (staging / "tok-good" / "plan.md").exists()
    assert (staging / "tok-bad" / "plan.md").exists()


def test_add_defer_then_finalize_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end via the CLI: defer two, finalize, both materialize and validate.
    monkeypatch.chdir(tmp_path)
    assert (
        runner.invoke(app, ["add", "one", "--title", "One", "--defer"]).exit_code == 0
    )
    assert (
        runner.invoke(app, ["add", "two", "--title", "Two", "--defer"]).exit_code == 0
    )
    result = runner.invoke(app, ["finalize", "--no-commit"])
    assert result.exit_code == 0, result.output
    plans = tmp_path / ".planners" / "plans"
    materialized = sorted(p.name for p in plans.glob("0*-*"))
    # Both back-to-back defers may land in the same clock-second, so the
    # number<->slug order is not fixed; assert the set instead: two sequential
    # numbers across the two slugs, each valid.
    assert {n.split("-", 1)[0] for n in materialized} == {"000", "001"}
    assert {n.split("-", 1)[1] for n in materialized} == {"one", "two"}
    for d in materialized:
        assert PlanMetadata.from_file(plans / d / "plan.md").validate() == []
    # staging cleaned up
    assert not (tmp_path / ".planners" / "staging").exists()


# --- activate -----------------------------------------------------------------

_DRAFT_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: draft\nbranch:\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
    "# My thing\n\n## Plan\n\nBody text that must survive verbatim.\n"
)


def _commit_all(path: Path, message: str) -> None:
    """Stage everything and commit, so HEAD is born and the guard is reachable."""
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=path, check=True)


def _git_log(path: Path) -> str:
    return subprocess.run(
        ["git", "log", "--oneline"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_activate_no_commit_flips_status_and_derives_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 0, result.output

    text = (tmp_path / ".planners" / "plans" / "005-my-thing" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert "status: active" in text
    assert "branch: feature/my-thing" in text
    # The body is preserved verbatim — only the frontmatter is re-rendered.
    assert "Body text that must survive verbatim." in text
    assert "# My thing" in text
    # --no-commit refreshes nothing and commits nothing.
    assert not (tmp_path / ".planners" / "README.md").exists()


def test_activate_accepts_bare_and_padded_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["activate", "5", "--no-commit"]).exit_code == 0


def test_activate_number_does_not_match_by_string_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `5` must not resolve to 050; matching is on the parsed number, not a prefix.
    _write_plan(
        tmp_path / ".planners" / "plans",
        "050-my-thing",
        _DRAFT_PLAN.replace("id: 5\n", "id: 50\n"),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["activate", "5", "--no-commit"])
    assert result.exit_code == 1
    assert "no plan 005 found" in result.output


def test_activate_resolves_subplan_letter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "005-umbrella", _DRAFT_PLAN.replace("my-thing", "umbrella"))
    _write_plan(
        plans,
        "005a-step-one",
        _DRAFT_PLAN.replace("slug: my-thing", "slug: step-one\nsub: a"),
    )
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["activate", "005a", "--no-commit"]).exit_code == 0
    # The umbrella is untouched: 005a and 005 are different plans.
    assert "status: draft" in (plans / "005-umbrella" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert "status: active" in (plans / "005a-step-one" / "plan.md").read_text(
        encoding="utf-8"
    )


def test_activate_rejects_malformed_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["activate", "my-thing", "--no-commit"])
    assert result.exit_code == 1
    assert "not a plan reference" in result.output


def test_activate_explicit_branch_overrides_derived_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["activate", "005", "--branch", "spike/other", "--no-commit"]
    )
    assert result.exit_code == 0, result.output
    text = (tmp_path / ".planners" / "plans" / "005-my-thing" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert "branch: spike/other" in text


def test_activate_leaves_populated_branch_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(
        tmp_path / ".planners" / "plans",
        "005-my-thing",
        _DRAFT_PLAN.replace("branch:\n", "branch: feature/already-chosen\n"),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["activate", "005", "--branch", "feature/ignored", "--no-commit"]
    )
    assert result.exit_code == 0, result.output
    text = (tmp_path / ".planners" / "plans" / "005-my-thing" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert "branch: feature/already-chosen" in text
    assert "feature/ignored" not in text


def test_activate_reactivates_an_inactive_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A parked plan may be revisited; the convention says so explicitly.
    _write_plan(
        tmp_path / ".planners" / "plans",
        "005-my-thing",
        _DRAFT_PLAN.replace("status: draft", "status: inactive"),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "status: active" in (
        tmp_path / ".planners" / "plans" / "005-my-thing" / "plan.md"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("closed", ["done", "retired"])
def test_activate_refuses_a_closed_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, closed: str
) -> None:
    original = _DRAFT_PLAN.replace("status: draft", f"status: {closed}").replace(
        "concluded:\n", "concluded: 2026-06-08T12:00:00-07:00\n"
    )
    path = _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", original)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 1
    assert "it is closed" in result.output
    # A refusal leaves the plan byte-for-byte untouched.
    assert path.read_text(encoding="utf-8") == original


def test_activate_on_already_active_plan_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _DRAFT_PLAN.replace("status: draft", "status: active").replace(
        "branch:\n", "branch: feature/my-thing\n"
    )
    path = _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", original)
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)
    _commit_all(tmp_path, "initial commit")

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert "already active" in result.output
    # Nothing rewritten and — crucially — no empty commit attempted.
    assert path.read_text(encoding="utf-8") == original
    assert "plan [activate]" not in _git_log(tmp_path)


def test_activate_commits_by_default_with_slug_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)
    _commit_all(tmp_path, "initial commit")

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    # The subject names the slug, not the title ("My thing").
    assert "plan [activate]: 005 - my-thing" in _git_log(tmp_path)
    # The index was refreshed and committed alongside the plan.
    readme = (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert "active" in readme
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )


def test_activate_fills_an_empty_branch_on_an_already_active_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-op fires only when nothing would change — an empty branch: changes.

    Narrowing the condition to `already_active` alone would leave such a plan
    permanently unbranched, which is exactly the field activate exists to fill.
    """
    path = _write_plan(
        tmp_path / ".planners" / "plans",
        "005-my-thing",
        _DRAFT_PLAN.replace("status: draft", "status: active"),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "nothing to do" not in result.output
    assert "branch: feature/my-thing" in path.read_text(encoding="utf-8")


def test_activate_commits_an_explicit_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--branch travels the committing path, not just the --no-commit one."""
    path = _write_plan(tmp_path / ".planners" / "plans", "005-my-thing", _DRAFT_PLAN)
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)
    _commit_all(tmp_path, "initial commit")

    result = runner.invoke(app, ["activate", "005", "--branch", "spike/other"])
    assert result.exit_code == 0, result.output
    # The chosen branch is what lands in the file — not the derived feature/<slug>.
    assert "branch: spike/other" in path.read_text(encoding="utf-8")
    assert "feature/my-thing" not in path.read_text(encoding="utf-8")
    # The subject still names the slug, and the index was refreshed alongside it.
    assert "plan [activate]: 005 - my-thing" in _git_log(tmp_path)
    assert "active" in (tmp_path / ".planners" / "README.md").read_text(
        encoding="utf-8"
    )


# --- validate: the index must agree with the frontmatter it is generated from --


def test_validate_flags_an_index_that_disagrees_with_the_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", "."]).exit_code == 0
    # the index is fresh, so validate passes
    assert runner.invoke(app, ["validate", "."]).exit_code == 0

    # now the index says something the frontmatter does not — the state a merge
    # leaves behind (merge=union can duplicate a row), and the state a plan edited
    # without reindexing leaves behind.
    index = tmp_path / ".planners" / "README.md"
    index.write_text(index.read_text(encoding="utf-8") + "| 099 | stray |\n", "utf-8")

    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 1
    assert "stale" in result.output
    assert "planners index ." in result.output


def test_validate_checks_the_index_when_handed_a_single_plan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # How the pre-commit hook calls it: pre-commit passes the matched *filenames*,
    # never a repo root, so a check that only fired for a directory argument would
    # never fire where it matters most.
    plans = tmp_path / ".planners" / "plans"
    plan = _write_plan(plans, "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", "."]).exit_code == 0
    index = tmp_path / ".planners" / "README.md"
    index.write_text("# Plans\n\nnot what the frontmatter says\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == 1
    assert "stale" in result.output


def test_validate_does_not_invent_a_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Absence is `install`/`add`'s business, not validate's: a checkout that has
    # never generated an index must not be failed for it.
    _write_plan(tmp_path / ".planners" / "plans", "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".planners" / "README.md").exists()
    assert runner.invoke(app, ["validate", "."]).exit_code == 0


def test_validate_ignores_a_legacy_layout_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A repo mid-migration: plans still under docs/plans/, and a .planners index
    # that describes the (empty) new tree. A legacy plan must not be attributed to
    # that index — matching on `plans` alone would do exactly that, and report a
    # stale index for a plan the index was never generated from.
    plan = _write_plan(tmp_path / "docs" / "plans", "001-thing", _VALID_PLAN)
    (tmp_path / ".planners" / "plans").mkdir(parents=True)
    (tmp_path / ".planners" / "README.md").write_text(
        "# Plans\n\n| 001 | a row the new tree does not have |\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == 0, result.output


def test_validate_survives_a_plan_file_with_no_room_for_a_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A path too shallow to hold the .planners/plans/<dir>/ shape must read as
    # "not our layout", not index past the end of its parents.
    (tmp_path / "plan.md").write_text(_VALID_PLAN, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", "plan.md"])
    assert result.exit_code == 0, result.output


def test_validate_accepts_an_index_generated_with_cols_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `index --cols all` is a first-class documented option, so a wide index is a
    # legitimate tracked state. Comparing only against the curated rendering
    # reported such a repo stale on every commit, with no edit able to fix it —
    # the pre-commit hook would have blocked the repo outright.
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", ".", "--cols", "all"]).exit_code == 0
    index = (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert "Branch" in index  # the wide header, not the curated one

    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 0, result.output


def test_validate_warns_once_per_bad_plan_not_once_per_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stale check re-parses every plan in the repo, so testing it once per
    # matched FILE (dedup after the filter) both made `validate .` quadratic in
    # the plan count and repeated _collect_metas's skip-warning per file — one
    # malformed plan read as many.
    plans = tmp_path / ".planners" / "plans"
    for name in ("001-thing", "002-thing", "003-thing"):
        _write_plan(plans, name, _VALID_PLAN.replace("id: 1", f"id: {name[2]}"))
    _write_plan(plans, "004-bad", "not a plan at all\n")
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["index", "."])

    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 1
    assert result.output.count("warning: skipping") == 1


def test_validate_summarizes_a_stale_index_only_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every other failure path ends in a summary line; a stale-index-only run
    # exited 1 with none, leaving the exit code as the only signal.
    plans = tmp_path / ".planners" / "plans"
    _write_plan(plans, "001-thing", _VALID_PLAN)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", "."]).exit_code == 0
    index = tmp_path / ".planners" / "README.md"
    index.write_text(index.read_text(encoding="utf-8") + "| 099 | stray |\n", "utf-8")

    result = runner.invoke(app, ["validate", "."])
    assert result.exit_code == 1
    assert "1 stale index file(s)" in result.output
