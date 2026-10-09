"""Tests for the standard Log entries in ``planners.entries``."""

import pytest

from planners import entries

_WHEN = "2026-01-01T12:00:00-08:00"


def test_activation_entry_has_every_field() -> None:
    entry = entries.activation_entry(
        _WHEN,
        branch="feature/thing",
        base="dev",
        sha="abc1234",
        worktree=".worktrees/thing",
        pr=None,
    )
    assert entry == (
        f"- **{_WHEN}** — Activated.\n"
        "  - Branch: `feature/thing`\n"
        "  - Base: `dev` at `abc1234`\n"
        "  - Worktree: `.worktrees/thing`\n"
        "  - PR: pending"
    )


def test_activation_entry_unknown_base_and_main_checkout() -> None:
    entry = entries.activation_entry(
        _WHEN,
        branch="feature/thing",
        base=None,
        sha=None,
        worktree=entries.NO_WORKTREE,
        pr="https://github.com/owner/repo/pull/1",
    )
    assert "  - Base: a detached HEAD (no commits yet)" in entry
    # The sentinel is prose, not a path, so it is not set in code.
    assert "  - Worktree: none (main checkout)" in entry
    assert "  - PR: https://github.com/owner/repo/pull/1" in entry


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("feature/thing", ".worktrees/thing"),
        ("thing", ".worktrees/thing"),
        ("spike/deep/thing/", ".worktrees/thing"),
    ],
)
def test_default_worktree_is_the_branch_suffix(branch: str, expected: str) -> None:
    assert entries.default_worktree(branch) == expected


@pytest.mark.parametrize(
    "path", ["/home/someone/repo/.worktrees/x", "C:\\repo\\x", "~/repo/x", "  "]
)
def test_worktree_error_refuses_paths_that_are_not_repo_relative(path: str) -> None:
    assert entries.worktree_error(path) is not None


@pytest.mark.parametrize("path", [".worktrees/x", "trees/x", "x"])
def test_worktree_error_accepts_repo_relative_paths(path: str) -> None:
    assert entries.worktree_error(path) is None


def test_one_line_entries() -> None:
    assert entries.pr_entry(_WHEN, "https://x/pull/2") == (
        f"- **{_WHEN}** — PR opened: https://x/pull/2"
    )
    assert entries.reactivation_entry(_WHEN).startswith(f"- **{_WHEN}** — Reactivated")
    assert entries.implemented_entry(_WHEN, 3, "dev") == (
        f"- **{_WHEN}** — Implemented: 3 commits ahead of `dev`."
    )
    assert entries.implemented_entry(_WHEN, 1, "dev").endswith(
        "1 commit ahead of `dev`."
    )
    # An unmeasured count is left out, not guessed.
    assert entries.implemented_entry(_WHEN, None, "dev") == (
        f"- **{_WHEN}** — Implemented."
    )


def test_recorded_base_reads_the_last_activation_in_the_log() -> None:
    text = (
        "# Thing\n\n## Plan\n\n```markdown\n- Base: `example` at `0000000`\n```\n\n"
        "- Base: `spec-prose`\n\n"
        "## Log\n\n"
        "- **t1** — Activated.\n  - Base: `main` at `1111111`\n"
        "- **t2** — Activated.\n  - Base: `dev` at `2222222`\n\n"
        "## Retrospective\n\n- Base: `after`\n"
    )
    assert entries.recorded_base(text) == "dev"


def test_recorded_base_skips_a_fenced_example_inside_the_log() -> None:
    text = "## Log\n\n```\n- Base: `example`\n```\n"
    assert entries.recorded_base(text) is None


def test_recorded_base_without_a_log() -> None:
    assert entries.recorded_base("# Thing\n\n## Plan\n") is None
