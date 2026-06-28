"""Tests for bundled convention-rule emission (mirrors test_skill.py)."""

import pytest

from planners.rule import RULE_NAMES, get_rule, list_rules


def test_list_rules_is_the_planners_convention() -> None:
    # The rule is named `planners` (installs tool-namespaced as planners.md),
    # never the legacy `plan-files`.
    assert list_rules() == ["planners"]
    assert "plan-files" not in RULE_NAMES


def test_get_rule_strips_frontmatter() -> None:
    body = get_rule("planners")
    assert not body.startswith("---")
    assert body.startswith("# Plan Files")


@pytest.mark.parametrize("name", RULE_NAMES)
def test_every_rule_loads_and_is_non_trivial(name: str) -> None:
    body = get_rule(name)
    assert len(body) > 200
    assert not body.startswith("---")


def test_unknown_rule_raises() -> None:
    with pytest.raises(KeyError):
        get_rule("nope")


@pytest.mark.parametrize("name", RULE_NAMES)
def test_no_rule_leaves_cli_placeholder(name: str) -> None:
    # A leftover {cli} token would print a literal "{cli}" into the rule file.
    assert "{cli}" not in get_rule(name, "global")
    assert "{cli}" not in get_rule(name, "local")


@pytest.mark.parametrize("name", RULE_NAMES)
def test_global_render_has_no_uv_run_planners(name: str) -> None:
    # A global rule invokes the CLI bare; any `uv run` would be a non-planners
    # tool reference (there are none in the convention body — the gate).
    assert "uv run planners" not in get_rule(name, "global")


def test_get_rule_renders_invocation_per_mode() -> None:
    glob = get_rule("planners", "global")
    local = get_rule("planners", "local")
    # The body invokes the CLI as inline code; backtick-anchored so the global
    # positive can't be satisfied by the local form (`planners index .` is a
    # substring of `uv run planners index .`, but the backtick before `planners`
    # is not — local puts `uv run ` there instead).
    assert "`planners index .`" in glob
    assert "`uv run planners index .`" not in glob
    assert "`uv run planners index .`" in local


def test_get_rule_defaults_to_global() -> None:
    assert get_rule("planners") == get_rule("planners", "global")
