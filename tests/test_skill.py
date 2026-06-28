"""Tests for bundled skill emission."""

import pytest

from planners.skill import SKILL_NAMES, get_skill, list_skills, render_prompt


def test_list_skills_is_the_seven_lifecycle_names() -> None:
    assert list_skills() == [
        "add",
        "implement",
        "update",
        "close",
        "pipeline",
        "index",
        "backfill",
    ]


def test_render_prompt_strips_frontmatter_and_substitutes_cli() -> None:
    # The shared transform behind both skill and rule emission: drop frontmatter,
    # render {cli} for the mode, ensure a trailing newline.
    text = "---\nname: x\n---\n\nrun `{cli} index .` here\n"
    glob = render_prompt(text, "global")
    assert glob == "run `planners index .` here\n"
    local = render_prompt(text, "local")
    assert local == "run `uv run planners index .` here\n"


def test_render_prompt_defaults_to_global() -> None:
    assert render_prompt("`{cli}`") == render_prompt("`{cli}`", "global")


def test_render_prompt_passes_through_text_without_frontmatter() -> None:
    # No opening fence -> the body is the input verbatim (lossless), {cli}-rendered.
    assert render_prompt("# Heading\n\nbody\n", "global") == "# Heading\n\nbody\n"


def test_get_skill_strips_frontmatter() -> None:
    body = get_skill("add")
    assert not body.startswith("---")
    assert "name: add" not in body
    assert body.startswith("# add")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skill_loads_and_is_non_trivial(name: str) -> None:
    body = get_skill(name)
    assert len(body) > 200
    assert not body.startswith("---")


def test_unknown_skill_raises() -> None:
    with pytest.raises(KeyError):
        get_skill("nope")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_no_skill_leaves_cli_placeholder(name: str) -> None:
    # The {cli} token must be substituted in every mode — a leftover token would
    # print a literal "{cli}" to the user.
    assert "{cli}" not in get_skill(name, "global")
    assert "{cli}" not in get_skill(name, "local")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_global_render_has_no_uv_run_planners(name: str) -> None:
    # The per-body "prefix with uv run" note is gone; a global body invokes the
    # CLI bare. Any remaining `uv run` is non-planners repo tooling (the gate).
    assert "uv run planners" not in get_skill(name, "global")


def test_get_skill_renders_invocation_per_mode() -> None:
    # index.md invokes the CLI, so the rendered prefix differs by mode.
    glob = get_skill("index", "global")
    local = get_skill("index", "local")
    # newline-anchored so the global positive can't be satisfied by the local
    # form (`planners index .` is a substring of `uv run planners index .`).
    assert "\nplanners index ." in glob
    assert "uv run planners index ." not in glob
    assert "uv run planners index ." in local


def test_get_skill_defaults_to_global() -> None:
    assert get_skill("index") == get_skill("index", "global")
