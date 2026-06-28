"""End-to-end tests for the CLI commands via Typer's runner."""

import subprocess
from importlib import metadata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import install as install_mod
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


def test_skill_list_and_body() -> None:
    listed = runner.invoke(app, ["skill", "--list"])
    assert listed.exit_code == 0
    assert "add" in listed.output

    body = runner.invoke(app, ["skill", "add"])
    assert body.exit_code == 0
    assert body.output.lstrip().startswith("# add")


def test_skill_unknown_exits_nonzero() -> None:
    assert runner.invoke(app, ["skill", "nope"]).exit_code == 1


def test_rule_list_and_body() -> None:
    listed = runner.invoke(app, ["rule", "--list"])
    assert listed.exit_code == 0
    assert "planners" in listed.output

    body = runner.invoke(app, ["rule", "planners"])
    assert body.exit_code == 0
    assert body.output.lstrip().startswith("# Plan Files")


def test_rule_unknown_exits_nonzero() -> None:
    assert runner.invoke(app, ["rule", "nope"]).exit_code == 1


def test_rule_renders_invocation_for_installed_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `rule` resolves the installed holder's mode so its printed commands are
    # runnable as-is: a local install renders `uv run planners`, a global one bare.
    repo = _isolate_home(tmp_path, monkeypatch)

    assert runner.invoke(app, ["install"]).exit_code == 0  # local holder
    local_body = runner.invoke(app, ["rule", "planners"])
    assert local_body.exit_code == 0
    assert "`uv run planners index .`" in local_body.output

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0  # switch
    assert not (repo / ".claude" / "skills" / "planners" / "SKILL.md").exists()
    global_body = runner.invoke(app, ["rule", "planners"])
    assert global_body.exit_code == 0
    assert "`uv run planners index .`" not in global_body.output
    assert "`planners index .`" in global_body.output


def test_skill_renders_invocation_for_installed_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `skill` resolves the installed holder's mode so its printed commands are
    # runnable as-is: a local install renders `uv run planners`, a global one
    # renders bare `planners`.
    repo = _isolate_home(tmp_path, monkeypatch)

    assert runner.invoke(app, ["install"]).exit_code == 0  # local holder
    local_body = runner.invoke(app, ["skill", "index"])
    assert local_body.exit_code == 0
    assert "uv run planners index ." in local_body.output

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0  # switch
    # the local holder must be gone, else the global resolution would be reading
    # the wrong holder and this test could pass for the wrong reason.
    assert not (repo / ".claude" / "skills" / "planners" / "SKILL.md").exists()
    global_body = runner.invoke(app, ["skill", "index"])
    assert global_body.exit_code == 0
    assert "uv run planners index ." not in global_body.output
    # newline-anchored: `planners index .` alone is a substring of the local form.
    assert "\nplanners index ." in global_body.output


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


def test_install_local_writes_repo_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate $HOME so the install's shadow check can't read the developer's real
    # ~/.claude/skills/planners/SKILL.md.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    holder = repo / ".claude" / "skills" / "planners" / "SKILL.md"
    assert holder.exists()
    body = holder.read_text(encoding="utf-8")
    assert "(mode=local)" in body
    assert "uv run planners install --check" in body
    # local mode does not bootstrap repo content
    assert not (repo / ".planners").exists()
    config = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: uv run planners validate" in config


def test_install_refuses_drifted_holder_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    assert runner.invoke(app, ["install"]).exit_code == 0
    holder = repo / ".claude" / "skills" / "planners" / "SKILL.md"
    holder.write_text(
        holder.read_text(encoding="utf-8") + "\nhand-edit\n", encoding="utf-8"
    )

    drifted = runner.invoke(app, ["install"])
    assert drifted.exit_code == 1
    # message names the path and says overwrite (not "regenerate"), since the
    # blocking file may not even be a planners holder
    assert str(holder) in drifted.output
    assert "--force" in drifted.output
    assert "overwrite" in drifted.output

    # --force gets through and rewrites it, after announcing what it overwrites.
    # CliRunner's stdin is not a TTY, so the confirmation prints its context and
    # proceeds without blocking on an Enter.
    forced = runner.invoke(app, ["install", "--force"])
    assert forced.exit_code == 0
    assert str(holder) in forced.output
    assert "planners-generated holder" in forced.output  # ours: safe to regenerate
    assert "not a TTY" in forced.output
    assert "hand-edit" not in holder.read_text(encoding="utf-8")


def test_install_force_warns_when_overwriting_a_foreign_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    # a non-planners file squatting at the holder path (no generated marker)
    holder = repo / ".claude" / "skills" / "planners" / "SKILL.md"
    holder.parent.mkdir(parents=True)
    holder.write_text("name: planners\nmy own skill\n", encoding="utf-8")

    forced = runner.invoke(app, ["install", "--force"])
    assert forced.exit_code == 0
    # the warning must flag that this is NOT ours and content is being lost
    assert "NOT a planners-generated file" in forced.output
    assert "contents will be lost" in forced.output
    assert "my own skill" not in holder.read_text(encoding="utf-8")


def test_install_check_notes_shadowed_local_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    # a repo with both a per-repo holder and a global holder (the shadow case)
    assert runner.invoke(app, ["install"]).exit_code == 0
    install_mod.write_holder(repo, "9.9.9", "global")

    checked = runner.invoke(app, ["install", "--check"])
    # the note must fire so the local stub's self-check isn't silently reporting
    # on the global holder that actually takes precedence
    assert "both a global and a per-repo" in checked.output


def test_install_global_writes_home_holder_and_bootstraps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["install", "--global"])
    assert result.exit_code == 0, result.output

    holder = home / ".claude" / "skills" / "planners" / "SKILL.md"
    assert holder.exists()
    body = holder.read_text(encoding="utf-8")
    assert "(mode=global)" in body
    assert "uv run planners" not in body

    # the per-repo hook uses the bare entry, and the plans folder is ensured
    config = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: planners validate" in config
    assert (repo / ".planners" / "plans").is_dir()
    # no per-repo holder was written under global mode
    assert not (repo / ".claude" / "skills" / "planners" / "SKILL.md").exists()


def test_install_global_removes_stale_local_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    # an existing local install...
    assert runner.invoke(app, ["install"]).exit_code == 0
    local_holder = repo / ".claude" / "skills" / "planners" / "SKILL.md"
    assert local_holder.exists()

    # ...switched to global must not leave the local holder shadowing the global one
    result = runner.invoke(app, ["install", "--global"])
    assert result.exit_code == 0, result.output
    assert not local_holder.exists()
    assert (home / ".claude" / "skills" / "planners" / "SKILL.md").exists()
    assert "removed stale local holder" in result.output


def test_install_global_reinstall_keeps_local_hook_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A same-mode global re-install (e.g. refreshing the shared global holder)
    # must not rewrite a repo's deliberate `uv run planners validate` entry — the
    # case that kept clobbering the planners dev repo's committed hook config.
    repo = _isolate_home(tmp_path, monkeypatch)
    version = metadata.version("planners")
    # the repo keeps a local-invocation hook entry...
    install_mod.wire_precommit(repo, "local")
    # ...while already using the shared global holder (no per-repo holder)
    install_mod.write_holder(repo, version, "global")

    result = runner.invoke(app, ["install", "--global"])
    assert result.exit_code == 0, result.output
    config = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: uv run planners validate" in config
    assert "entry: planners validate" not in config


def test_install_check_recovers_global_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0
    # --check takes no mode flag and still reports ok against the global holder;
    # it reports the holder and the rule per artifact.
    checked = runner.invoke(app, ["install", "--check"])
    assert checked.exit_code == 0
    assert "holder: ok" in checked.output
    assert "rule:   ok" in checked.output


def test_install_global_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0
    holder = (home / ".claude" / "skills" / "planners" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    config = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    second = runner.invoke(app, ["install", "--global"])
    assert second.exit_code == 0
    assert "pre-commit hook config already present" in second.output
    # re-install is byte-stable
    assert (home / ".claude" / "skills" / "planners" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == holder
    assert (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8") == config


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate $HOME and chdir into a fresh repo dir; return the repo path."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)
    return repo


def test_install_config_only_message_outside_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In a non-git dir the hook cannot be registered; the message must name that
    # cause honestly (run `git init`) rather than telling the user to run
    # `pre-commit install`, which needs a git repo and would fail.
    _isolate_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "not a git repository" in result.output
    assert "hook activated" not in result.output


def test_install_config_only_message_when_pre_commit_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In a git repo where activation fails (pre-commit not runnable), the message
    # must say the hook is NOT active and point at the install command + --full.
    repo = _isolate_home(tmp_path, monkeypatch)
    (repo / ".git").mkdir()
    monkeypatch.setattr(install_mod, "_run_precommit_install", lambda _root: False)
    # Pin core.hooksPath unset so this exercises the pre-commit-unavailable branch
    # and not hookspath_blocked if the developer has a global core.hooksPath.
    monkeypatch.setattr(install_mod, "core_hookspath_set", lambda _root: False)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "NOT active" in result.output
    assert "--full" in result.output
    assert "hook activated" not in result.output


def test_install_reports_already_active_under_core_hookspath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The field case at the CLI layer: a real repo whose pre-commit hook
    # lives at a configured core.hooksPath must report "already active", never a
    # false "NOT active" / a re-attempted (doomed) install.
    repo = _isolate_home(tmp_path, monkeypatch)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    hooks = repo / "myhooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text(
        "#!/bin/sh\n# File generated by pre-commit\n", encoding="utf-8"
    )
    subprocess.run(["git", "config", "core.hooksPath", "myhooks"], cwd=repo, check=True)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "pre-commit hook already active" in result.output
    assert "NOT active" not in result.output
    assert "core.hooksPath" not in result.output


def test_install_hookspath_blocked_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When git's core.hooksPath is set, `pre-commit install` refuses. The message
    # must name that cause and the real remedy (unset core.hooksPath) rather than
    # the catch-all "pre-commit unavailable", which would send the user to a
    # command that refuses the same way.
    repo = _isolate_home(tmp_path, monkeypatch)
    (repo / ".git").mkdir()
    monkeypatch.setattr(install_mod, "_precommit_hook_registered", lambda _root: False)
    monkeypatch.setattr(install_mod, "core_hookspath_set", lambda _root: True)
    monkeypatch.setattr(
        install_mod,
        "_run_precommit_install",
        lambda _root: pytest.fail("hookspath_blocked must not shell out to install"),
    )
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "core.hooksPath" in result.output
    assert "git config --unset-all core.hooksPath" in result.output
    assert "NOT active" in result.output
    # the misdiagnosis this branch removes must not appear
    assert "pre-commit unavailable" not in result.output
    assert "hook activated" not in result.output


def test_install_activated_message_when_hook_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setattr(
        install_mod, "activate_precommit", lambda _root, *, attempt=True: "activated"
    )
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "pre-commit hook activated" in result.output


def test_install_no_activate_skips_and_instructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    # a git repo so the only reason activation is skipped is --no-activate
    (repo / ".git").mkdir()
    monkeypatch.setattr(
        install_mod,
        "_run_precommit_install",
        lambda _root: pytest.fail("--no-activate must not shell out"),
    )
    result = runner.invoke(app, ["install", "--no-activate"])
    assert result.exit_code == 0, result.output
    assert "skipped hook activation" in result.output


def test_install_full_adds_dependency_then_activates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_home(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        install_mod,
        "ensure_precommit_dependency",
        lambda _root: calls.append("dep") or True,
    )
    monkeypatch.setattr(
        install_mod, "activate_precommit", lambda _root, *, attempt=True: "activated"
    )
    result = runner.invoke(app, ["install", "--full"])
    assert result.exit_code == 0, result.output
    assert calls == ["dep"]
    assert "added pre-commit dev dependency" in result.output
    assert "pre-commit hook activated" in result.output


def test_install_full_warns_when_dependency_add_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setattr(install_mod, "ensure_precommit_dependency", lambda _root: False)
    result = runner.invoke(app, ["install", "--full"])
    assert result.exit_code == 0, result.output
    assert "uv add --dev pre-commit` did not succeed" in result.output


def test_install_full_and_no_activate_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["install", "--full", "--no-activate"])
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


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


# --- install: the convention rule artifact -----------------------------------


def test_install_local_writes_repo_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    assert runner.invoke(app, ["install"]).exit_code == 0
    rule = repo / ".claude" / "rules" / "planners.md"
    assert rule.exists()
    body = rule.read_text(encoding="utf-8")
    assert body.startswith("<!-- generated by planners ")
    assert "(mode=local)" in body
    assert "# Plan Files" in body
    assert "`uv run planners index .`" in body


def test_install_global_writes_home_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0
    rule = home / ".claude" / "rules" / "planners.md"
    assert rule.exists()
    body = rule.read_text(encoding="utf-8")
    assert "(mode=global)" in body
    assert "uv run planners" not in body
    # no per-repo rule was written under global mode
    assert not (repo / ".claude" / "rules" / "planners.md").exists()


def test_install_no_rule_skips_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["install", "--no-rule"])
    assert result.exit_code == 0
    assert not (repo / ".claude" / "rules" / "planners.md").exists()
    # the holder is still written — --no-rule only skips the rule
    assert (repo / ".claude" / "skills" / "planners" / "SKILL.md").exists()


def test_install_refuses_drifted_rule_then_force_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    assert runner.invoke(app, ["install"]).exit_code == 0
    rule = repo / ".claude" / "rules" / "planners.md"
    # a sentinel that is not a substring of the canonical body (the body itself
    # says "do not hand-edit", so use a distinctive marker here)
    sentinel = "ZZZ-DRIFT-SENTINEL"
    rule.write_text(
        rule.read_text(encoding="utf-8") + f"\n{sentinel}\n", encoding="utf-8"
    )

    # blocked without --force (the holder is unchanged, so the rule is the blocker)
    blocked = runner.invoke(app, ["install"])
    assert blocked.exit_code == 1
    assert str(rule) in blocked.output
    assert "--force" in blocked.output

    # --force regenerates it, announcing it is a planners-generated rule
    forced = runner.invoke(app, ["install", "--force"])
    assert forced.exit_code == 0
    assert "planners-generated rule" in forced.output
    assert sentinel not in rule.read_text(encoding="utf-8")


def test_install_force_warns_when_overwriting_a_foreign_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    # a non-planners file squatting at the rule path (no generated marker)
    rule = repo / ".claude" / "rules" / "planners.md"
    rule.parent.mkdir(parents=True)
    rule.write_text("# Plan Files\n\nmy own rule\n", encoding="utf-8")

    forced = runner.invoke(app, ["install", "--force"])
    assert forced.exit_code == 0
    assert "NOT a planners-generated file" in forced.output
    assert "my own rule" not in rule.read_text(encoding="utf-8")


def test_install_global_removes_stale_local_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)

    assert runner.invoke(app, ["install"]).exit_code == 0  # local rule
    local_rule = repo / ".claude" / "rules" / "planners.md"
    assert local_rule.exists()

    result = runner.invoke(app, ["install", "--global"])
    assert result.exit_code == 0, result.output
    assert not local_rule.exists()
    assert (home / ".claude" / "rules" / "planners.md").exists()
    assert "removed stale local rule" in result.output


def test_install_warns_about_superseded_plan_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    legacy = repo / ".claude" / "rules" / "plan-files.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Plan Files\n\nhand-maintained\n", encoding="utf-8")

    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "plan-files.md" in result.output
    assert "superseded" in result.output
    # the foreign legacy file is warned about, never deleted
    assert legacy.exists()


def test_install_check_reports_rule_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _isolate_home(tmp_path, monkeypatch)
    assert runner.invoke(app, ["install"]).exit_code == 0
    rule = repo / ".claude" / "rules" / "planners.md"
    rule.write_text(rule.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")

    checked = runner.invoke(app, ["install", "--check"])
    # a drifted rule gates the whole check just like a drifted holder
    assert checked.exit_code == 1
    assert "holder: ok" in checked.output
    assert "rule:   drifted" in checked.output


def test_install_check_flags_stale_per_repo_rule_after_global_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A repo switched to --global that kept a stale per-repo rule (e.g. the switch
    # ran with --no-rule, so the local copy was never removed). It is still
    # auto-loaded, so --check must report drifted and name the local path — the
    # case that slipped through as `ok` before checking both locations.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)
    version = metadata.version("planners")

    # current global install (holder + rule under $HOME)
    assert runner.invoke(app, ["install", "--global"]).exit_code == 0
    # a per-repo rule left behind whose content still matches its own render — a
    # stale leftover, not content drift; flagged because the repo is now global
    install_mod.write_artifact(repo, version, "local", install_mod.RULE)
    assert install_mod.check_artifact(repo, version, "local", install_mod.RULE) == "ok"

    checked = runner.invoke(app, ["install", "--check"])
    assert checked.exit_code == 1
    assert "holder: ok" in checked.output
    assert "rule:   drifted" in checked.output
    # the note names the stale local rule path so the drift is actionable
    local_rule = repo / ".claude" / "rules" / "planners.md"
    assert str(local_rule) in checked.output


def test_install_check_finds_local_only_rule_without_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A per-repo rule with no holder anywhere: the rule must read ok (present and
    # valid), not the pre-014 `missing` from the holder-resolved mode defaulting to
    # global and looking only under $HOME. The holder is independently missing.
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(repo)
    version = metadata.version("planners")

    install_mod.write_artifact(repo, version, "local", install_mod.RULE)

    checked = runner.invoke(app, ["install", "--check"])
    assert "holder: missing" in checked.output
    assert "rule:   ok" in checked.output
    # the holder is genuinely absent, so the overall check still gates
    assert checked.exit_code == 1


def test_install_check_no_rule_skips_the_rule_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `install --check --no-rule` is the symmetric escape hatch for a deliberately
    # rule-less install: the rule it never wrote must not fail --check.
    repo = _isolate_home(tmp_path, monkeypatch)
    assert runner.invoke(app, ["install", "--no-rule"]).exit_code == 0
    assert not (repo / ".claude" / "rules" / "planners.md").exists()

    # plain --check fails: the rule is genuinely missing
    plain = runner.invoke(app, ["install", "--check"])
    assert plain.exit_code == 1
    assert "rule:   missing" in plain.output

    # --check --no-rule skips the rule and passes on the holder alone
    skipped = runner.invoke(app, ["install", "--check", "--no-rule"])
    assert skipped.exit_code == 0
    assert "holder: ok" in skipped.output
    assert "rule:   skipped" in skipped.output


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
