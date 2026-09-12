"""The pkgskills host declaration, and the repo wiring planners layers on it."""

from pathlib import Path

import pytest
from pkgskills import precommit
from pkgskills.spec import SPEC, report
from pkgskills.testing import Sandbox, assert_prompt_commands, sandbox
from typer.testing import CliRunner

from planners.cli import app
from planners.host import HOST, SKILL_NAMES

runner = CliRunner()


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    """A pinned home and repo, with pre-commit and git unreachable.

    Hook registration shells out; making every such call a missing binary keeps
    the tests deterministic and off the developer's machine state.
    """

    def missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr(precommit, "run", missing)
    return sandbox(tmp_path, monkeypatch)


def test_host_skills_follow_the_agent_skills_spec() -> None:
    # The seven bodies are dispatcher sources, printed by `skill <sub>` and never
    # installed as skills of their own, so they stay flat `skills/<name>.md`
    # rather than `<name>/SKILL.md`; every other rule of the spec still applies.
    violations = [v for v in SPEC.check_host(HOST) if v.rule != "entry-file"]
    assert violations == [], report(violations, header="spec violations:")


def test_prompts_name_only_commands_the_cli_has() -> None:
    assert_prompt_commands(HOST, app)


def test_bare_skill_lists_the_lifecycle_bodies_in_order() -> None:
    result = runner.invoke(app, ["skill"])
    assert result.exit_code == 0, result.output
    assert result.output.split() == list(SKILL_NAMES)


def test_install_local_writes_stub_rule_hooks_and_merge_attribute(
    box: Sandbox,
) -> None:
    result = runner.invoke(app, ["install", "--local"])
    assert result.exit_code == 0, result.output
    repo = box.repo
    assert (repo / ".claude/skills/planners/SKILL.md").is_file()
    rule = (repo / ".claude/rules/planners.md").read_text(encoding="utf-8")
    assert "(mode=local)" in rule
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


def test_a_pre_adoption_holder_is_foreign_until_forced(box: Sandbox) -> None:
    holder = box.repo / ".claude/skills/planners/SKILL.md"
    holder.parent.mkdir(parents=True)
    holder.write_text(
        "---\nname: planners\ndescription: old\n---\n\n"
        "<!-- generated by planners 0.6.1 (mode=local); do not edit — run: "
        "uv run planners install --force -->\n",
        encoding="utf-8",
    )
    refused = runner.invoke(app, ["install", "--local"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert runner.invoke(app, ["install", "--local", "--force"]).exit_code == 0
    assert "via pkgskills" in holder.read_text(encoding="utf-8")


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
