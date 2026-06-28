"""Emit bundled skill bodies (frontmatter stripped).

The skill instructions ship as markdown under ``planners/prompts/skills/`` and
are the source of truth; the dispatcher prints them on demand. Editing a skill
body never requires reinstalling ``.claude/``.

Each body invokes this CLI through a ``{cli}`` placeholder; :func:`render_prompt`
substitutes it with the mode-correct prefix (``planners`` for a global install,
``uv run planners`` for a per-repo one) from the single source in
:func:`planners.install.invocation`, so a printed body always reads correctly for
the installed mode instead of carrying a hand-written "prefix with uv run" note.
:func:`render_prompt` is the shared transform behind both skill and rule emission
(see :mod:`planners.rule`), so the two never diverge.
"""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from planners.utils import split_frontmatter

if TYPE_CHECKING:
    from planners.install import Mode

_SKILLS_PACKAGE = "planners.prompts.skills"

# The seven plan-lifecycle subcommands, in lifecycle order. `pipeline` follows
# `close` because it chains implement -> work -> close as one driven run.
SKILL_NAMES = (
    "add",
    "implement",
    "update",
    "close",
    "pipeline",
    "index",
    "backfill",
)

# Placeholder the bodies use for this CLI's invocation, swapped for the
# mode-correct prefix at render time (single source: install.invocation).
_CLI_TOKEN = "{cli}"


def list_skills() -> list[str]:
    """Return the bundled skill names, in lifecycle order."""
    return list(SKILL_NAMES)


def render_prompt(text: str, mode: Mode = "global") -> str:
    """Strip a bundled prompt's frontmatter and render its ``{cli}`` for ``mode``.

    The shared transform behind both skill and rule emission: the leading YAML
    frontmatter (if any) is dropped, surrounding whitespace trimmed, every
    ``{cli}`` placeholder replaced with the mode-correct invocation prefix
    (``planners`` global, ``uv run planners`` local) from the single source in
    :func:`planners.install.invocation`, and a trailing newline ensured. ``mode``
    defaults to ``global`` — the refreshed default — for callers with no installed
    holder to resolve.
    """
    # Local import avoids a module-load cycle: install imports skill.list_skills.
    from planners.install import invocation

    _, body = split_frontmatter(text)
    return body.strip().replace(_CLI_TOKEN, invocation(mode)) + "\n"


def get_skill(name: str, mode: Mode = "global") -> str:
    """Return a bundled skill's body, frontmatter stripped and mode-rendered.

    The ``{cli}`` placeholder is replaced with the invocation prefix for ``mode``
    (``planners`` global, ``uv run planners`` local) so the printed commands run
    as-is, via the shared :func:`render_prompt`.
    """
    if name not in SKILL_NAMES:
        raise KeyError(name)
    text = (
        resources.files(_SKILLS_PACKAGE)
        .joinpath(f"{name}.md")
        .read_text(encoding="utf-8")
    )
    return render_prompt(text, mode)
