"""Emit the bundled convention rule body (frontmatter stripped).

Mirrors :mod:`planners.skill` for Claude Code's native rules system. The
convention prose ships as markdown under ``planners/prompts/rules/`` and is the
source of truth; ``planners rule`` prints it on demand, and ``planners install``
writes a version-stamped copy to ``.claude/rules/planners.md`` (per-repo) or
``~/.claude/rules/planners.md`` (global), where Claude Code auto-loads it.

The body invokes this CLI through a ``{cli}`` placeholder, substituted via the
shared :func:`planners.skill.render_prompt` for the mode-correct prefix, so the
printed rule reads correctly for the installed mode.
"""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from planners.skill import render_prompt

if TYPE_CHECKING:
    from planners.install import Mode

_RULES_PACKAGE = "planners.prompts.rules"

# The bundled convention rules, by name. Today just the plan-files convention,
# whose source prompt is ``planners.md`` and which installs tool-namespaced as
# ``.claude/rules/planners.md`` (never clobbering a user's own plan-files.md).
RULE_NAMES = ("planners",)


def list_rules() -> list[str]:
    """Return the bundled rule names."""
    return list(RULE_NAMES)


def get_rule(name: str, mode: Mode = "global") -> str:
    """Return a bundled rule's body, frontmatter stripped and mode-rendered.

    The ``{cli}`` placeholder is replaced with the invocation prefix for ``mode``
    (``planners`` global, ``uv run planners`` local) so the printed commands run
    as-is, via the shared :func:`planners.skill.render_prompt`.
    """
    if name not in RULE_NAMES:
        raise KeyError(name)
    text = (
        resources.files(_RULES_PACKAGE)
        .joinpath(f"{name}.md")
        .read_text(encoding="utf-8")
    )
    return render_prompt(text, mode)
