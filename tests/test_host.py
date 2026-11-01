"""The pkgskills host declaration, and the repo wiring planners layers on it."""

import subprocess
from pathlib import Path

import pytest
from pkgskills import precommit
from pkgskills.testing import (
    Sandbox,
    assert_prompt_commands,
    assert_spec_conformant,
    sandbox,
)
from typer.testing import CliRunner

from planners.cli import app
from planners.host import HOST, SKILL_NAMES

pytestmark = pytest.mark.no_repo

runner = CliRunner()


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    """A pinned home and a real repo, with pre-commit's shell-outs unreachable.

    Hook registration shells out; making every such call a missing binary keeps
    the tests deterministic and off the developer's machine state.
    """

    def missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr(precommit, "run", missing)
    pinned = sandbox(tmp_path, monkeypatch)
    # The sandbox's `.git` is an empty marker, which the CLI does not count.
    subprocess.run(["git", "init", "-q"], cwd=pinned.repo, check=True)
    return pinned


def test_host_skills_follow_the_agent_skills_spec() -> None:
    assert_spec_conformant(HOST)


def test_prompts_name_only_commands_the_cli_has() -> None:
    assert_prompt_commands(HOST, app)


def test_bare_skill_lists_the_lifecycle_bodies_in_order() -> None:
    result = runner.invoke(app, ["skill"])
    assert result.exit_code == 0, result.output
    assert result.output.split() == list(SKILL_NAMES)


def test_orchestrated_run_guidance_prints_as_a_doc_not_with_implement() -> None:
    doc = runner.invoke(app, ["doc", "orchestrated-run"])
    assert doc.exit_code == 0, doc.output
    assert doc.output.startswith("# An orchestrated run\n")
    assert "{cli}" not in doc.output

    implement = runner.invoke(app, ["skill", "implement"])
    assert implement.exit_code == 0, implement.output
    assert "An orchestrated run" not in implement.output
    assert "doc orchestrated-run" in implement.output


def test_install_local_writes_stub_rule_hooks_and_merge_attribute(
    box: Sandbox,
) -> None:
    result = runner.invoke(app, ["install", "--local"])
    assert result.exit_code == 0, result.output
    repo = box.repo
    assert (repo / ".claude/skills/planners/SKILL.md").is_file()
    rule = (repo / ".claude/rules/planners.md").read_text(encoding="utf-8")
    assert "`uv run planners validate`" in rule
    assert (repo / ".gitattributes").read_text(
        encoding="utf-8"
    ) == ".planners/README.md merge=union\n"

    config = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    validate, index = config.split("- id: planners-index")
    assert "entry: uv run planners validate" in validate
    assert "files: '^\\.planners/plans/[^/]+/plan\\.md$'" in validate
    assert "pass_filenames" not in validate
    assert "entry: uv run planners index ." in index
    assert "stages: [post-merge]" in index
    assert "always_run: true" in index
    assert "pass_filenames: false" in index
    assert "wrote planners-validate" in result.output
    assert "post-merge hook: unavailable" in result.output


@pytest.mark.parametrize(
    ("flags", "mode"),
    [(["--global"], "global"), (["--local"], "local"), ([], "global")],
    ids=["global", "local", "no-flag"],
)
def test_install_scope_flags_write_to_their_scope(
    box: Sandbox, flags: list[str], mode: str
) -> None:
    """A provisioning script passes these, and 0.6.x once dropped `--global`."""
    result = runner.invoke(app, ["install", *flags])
    assert result.exit_code == 0, result.output

    written, untouched = (
        (box.home, box.repo) if mode == "global" else (box.repo, box.home)
    )
    rule = (written / ".claude/rules/planners.md").read_text(encoding="utf-8")
    command = "planners validate" if mode == "global" else "uv run planners validate"
    assert f"`{command}`" in rule
    assert (written / ".claude/skills/planners/SKILL.md").is_file()
    assert (written / ".agents/skills/planners/SKILL.md").is_file()
    assert not (untouched / ".claude/rules/planners.md").exists()
    assert not (untouched / ".claude/skills/planners/SKILL.md").exists()
    assert not (untouched / ".agents/skills/planners/SKILL.md").exists()


@pytest.mark.parametrize(
    ("flags", "mode"),
    [(["--global"], "global"), (["--local"], "local")],
    ids=["global", "local"],
)
def test_install_scope_flags_are_accepted_with_check(
    box: Sandbox, flags: list[str], mode: str
) -> None:
    assert runner.invoke(app, ["install", *flags]).exit_code == 0
    checked = runner.invoke(app, ["install", *flags, "--check"])
    assert checked.exit_code == 0, checked.output
    assert f"ok      {mode}" in checked.output


def test_flagless_check_finds_a_flagless_install(box: Sandbox) -> None:
    assert runner.invoke(app, ["install"]).exit_code == 0
    checked = runner.invoke(app, ["install", "--check"])
    assert checked.exit_code == 0, checked.output
    assert "ok      global" in checked.output
    assert "ok      local" not in checked.output


def test_printed_bodies_render_the_installed_mode(box: Sandbox) -> None:
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    skill = runner.invoke(app, ["skill", "add"])
    assert skill.exit_code == 0
    assert "uv run planners add" in skill.output
    rule = runner.invoke(app, ["rule"])
    assert rule.exit_code == 0
    assert "uv run planners index ." in rule.output


def test_reinstall_keeps_an_existing_hook_entry(box: Sandbox) -> None:
    config = box.repo / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: planners-validate\n"
        "        name: custom\n        entry: uv run planners validate\n"
        "        language: system\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    text = config.read_text(encoding="utf-8")
    assert text.count("planners-validate") == 1
    assert "name: custom" in text
    assert "planners-index" in text


def test_check_passes_and_reports_hooks_without_gating(box: Sandbox) -> None:
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    checked = runner.invoke(app, ["install", "--local", "--check"])
    assert checked.exit_code == 0, checked.output
    assert "hook planners-validate" in checked.output
    assert "hook planners-index" in checked.output


def test_check_gates_on_a_missing_index_attribute(box: Sandbox) -> None:
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    (box.repo / ".gitattributes").unlink()
    checked = runner.invoke(app, ["install", "--local", "--check"])
    assert checked.exit_code == 1
    assert "merge=union" in checked.output


def test_a_drifted_attribute_is_left_alone_until_forced(box: Sandbox) -> None:
    attrs = box.repo / ".gitattributes"
    attrs.write_text(".planners/README.md merge=ours\n", encoding="utf-8")
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    assert "merge=ours" in attrs.read_text(encoding="utf-8")
    assert runner.invoke(app, ["install", "--local", "--force"]).exit_code == 0
    assert attrs.read_text(encoding="utf-8") == ".planners/README.md merge=union\n"


HOLDER = Path(".claude/skills/planners/SKILL.md")
RULE = Path(".claude/rules/planners.md")

# The stamps pre-adoption releases wrote, in their exact form.
OLD_STAMPS = {
    "global": (
        "<!-- generated by planners 0.6.1 (mode=global); do not edit — run: "
        "planners install --force -->"
    ),
    "local": (
        "<!-- generated by planners 0.6.1 (mode=local); do not edit — run: "
        "uv run planners install --force -->"
    ),
}


def _plant(root: Path, relative: Path, stamp: str, body: str = "old body") -> Path:
    """Write a file as an earlier release did: a rule opens with the stamp."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (
        "---\nname: planners\ndescription: old\n---\n\n" if relative == HOLDER else ""
    )
    path.write_text(f"{head}{stamp}\n\n{body}\n", encoding="utf-8")
    return path


def _row(output: str, relative: Path) -> list[str]:
    """The status and mode `install --check` prints for the file at ``relative``."""
    rows = [
        line.split()[:2]
        for line in output.splitlines()
        if line.split()[2:3] and line.split()[2].endswith(relative.as_posix())
    ]
    assert len(rows) == 1, output
    return rows[0]


@pytest.mark.parametrize("mode", ["global", "local"])
def test_an_old_stamp_upgrades_with_a_plain_install(box: Sandbox, mode: str) -> None:
    root = box.home if mode == "global" else box.repo
    flag = f"--{mode}"
    holder = _plant(root, HOLDER, OLD_STAMPS[mode])
    rule = _plant(root, RULE, OLD_STAMPS[mode])

    before = runner.invoke(app, ["install", flag, "--check"])
    assert before.exit_code == 1
    assert _row(before.output, HOLDER) == ["drifted", mode]
    assert _row(before.output, RULE) == ["drifted", mode]
    # The advice is the install below, and nothing that could replace other files.
    hints = [
        line
        for line in before.output.splitlines()
        if line.startswith(("repair:", "overwrite:"))
    ]
    assert len(hints) == 1, before.output
    assert hints[0].startswith("repair:")
    assert "--force" not in hints[0]

    installed = runner.invoke(app, ["install", flag])
    assert installed.exit_code == 0, installed.output
    for path in (holder, rule):
        text = path.read_text(encoding="utf-8")
        assert OLD_STAMPS[mode] not in text
        assert "old body" not in text

    after = runner.invoke(app, ["install", flag, "--check"])
    assert after.exit_code == 0, after.output
    assert _row(after.output, HOLDER) == ["ok", mode]
    assert _row(after.output, RULE) == ["ok", mode]


def test_an_old_stamp_overwrites_edits_under_it(box: Sandbox) -> None:
    """The stamp said not to edit, so the edit does not stop the upgrade."""
    holder = _plant(box.repo, HOLDER, OLD_STAMPS["local"], body="my own edit")
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    assert "my own edit" not in holder.read_text(encoding="utf-8")


def test_an_old_stamp_in_the_other_mode_is_rewritten(box: Sandbox) -> None:
    holder = _plant(box.repo, HOLDER, OLD_STAMPS["global"])

    checked = runner.invoke(app, ["install", "--local", "--check"])
    assert checked.exit_code == 1
    assert _row(checked.output, HOLDER) == ["drifted", "local"]

    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    text = holder.read_text(encoding="utf-8")
    assert OLD_STAMPS["global"] not in text
    assert "uv run planners skill" in text


def test_a_global_install_removes_old_local_copies(box: Sandbox) -> None:
    holder = _plant(box.repo, HOLDER, OLD_STAMPS["local"])
    rule = _plant(box.repo, RULE, OLD_STAMPS["local"])

    assert runner.invoke(app, ["install", "--global"]).exit_code == 0

    assert not holder.exists()
    assert not rule.exists()
    assert (box.home / HOLDER).is_file()
    assert (box.home / RULE).is_file()


@pytest.mark.parametrize("mode", ["global", "local"])
def test_an_old_plan_files_rule_is_removed_in_its_own_scope(
    box: Sandbox, mode: str
) -> None:
    root = box.home if mode == "global" else box.repo
    old_rule = _plant(root, Path(".claude/rules/plan-files.md"), OLD_STAMPS[mode])
    assert runner.invoke(app, ["install", f"--{mode}"]).exit_code == 0
    assert not old_rule.exists()
    assert (root / RULE).is_file()


def test_a_hand_written_plan_files_rule_is_kept(box: Sandbox) -> None:
    path = box.repo / ".claude/rules/plan-files.md"
    path.parent.mkdir(parents=True)
    path.write_text("# My own plan rules\n", encoding="utf-8")
    assert runner.invoke(app, ["install", "--local"]).exit_code == 0
    assert path.read_text(encoding="utf-8") == "# My own plan rules\n"


@pytest.mark.parametrize(
    "stamp",
    [
        pytest.param(
            "<!-- generated by other 1.0.0 (mode=local); do not edit — run: "
            "uv run other install --force -->",
            id="another-dist",
        ),
        pytest.param("# Written by hand", id="no-stamp"),
        pytest.param(
            OLD_STAMPS["local"].replace("—", "-"),
            id="ascii-hyphen",
        ),
        pytest.param(f"{OLD_STAMPS['local']} and some prose", id="prose-after"),
        pytest.param(
            OLD_STAMPS["local"].replace("mode=local", "mode=both"),
            id="bad-mode",
        ),
    ],
)
def test_anything_else_is_refused_until_forced(box: Sandbox, stamp: str) -> None:
    holder = _plant(box.repo, HOLDER, stamp)
    planted = holder.read_text(encoding="utf-8")

    refused = runner.invoke(app, ["install", "--local"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert holder.read_text(encoding="utf-8") == planted

    assert runner.invoke(app, ["install", "--local", "--force"]).exit_code == 0
    assert holder.read_text(encoding="utf-8") != planted


def test_permissions_ladder() -> None:
    assist = runner.invoke(app, ["permissions", "--global"])
    assert assist.exit_code == 0, assist.output
    assert "Bash(planners:*)" in assist.output
    assert "Bash(git push:*)" not in assist.output
    local = runner.invoke(app, ["permissions", "--level", "confirm"])
    assert "Bash(git push:*)" in local.output
    assert "Bash(planners:*)" not in local.output
    full = runner.invoke(app, ["permissions", "--level", "full"])
    assert "Bash(gh pr merge:*)" in full.output
