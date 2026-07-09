"""Tests for the pure automation-level permission logic."""

import json
from pathlib import Path

import pytest

from planners.permissions import (
    LEVELS,
    Level,
    levels,
    merge_allow,
    parse_level,
    render_block,
    rules_for,
    settings_path,
)


def test_levels_are_the_four_names_low_to_high() -> None:
    assert levels() == ["none", "assist", "confirm", "full"]


def test_parse_level_roundtrips_names() -> None:
    for name in levels():
        assert parse_level(name).value == name


def test_parse_level_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        parse_level("unsupervised")


def test_none_grants_nothing() -> None:
    assert rules_for(Level.none, "local") == []
    assert rules_for(Level.none, "global") == []


def test_assist_is_local_spine_plus_self_authored_pr_writes() -> None:
    got = rules_for(Level.assist, "local")
    # The commit spine sits here, not with push — local and reversible.
    assert "Bash(git add:*)" in got
    assert "Bash(git commit:*)" in got
    assert "Bash(git worktree:*)" in got
    assert "Bash(uv run:*)" in got
    assert "Bash(gh pr comment:*)" in got
    assert "Bash(gh pr ready:*)" in got
    # ...but nothing that publishes code or is irreversible.
    assert "Bash(git push:*)" not in got
    assert "Bash(gh pr merge:*)" not in got


def test_planners_grant_is_global_only() -> None:
    # Global invokes bare `planners`; local runs `uv run planners`, already
    # covered by the `uv run:*` grant in assist.
    assert "Bash(planners:*)" in rules_for(Level.assist, "global")
    assert "Bash(planners:*)" not in rules_for(Level.assist, "local")


def test_confirm_adds_push_only() -> None:
    assist = set(rules_for(Level.assist, "local"))
    confirm = set(rules_for(Level.confirm, "local"))
    assert confirm - assist == {"Bash(git push:*)"}


def test_full_adds_merge_only() -> None:
    confirm = set(rules_for(Level.confirm, "local"))
    full = set(rules_for(Level.full, "local"))
    assert full - confirm == {"Bash(gh pr merge:*)"}


@pytest.mark.parametrize("mode", ["local", "global"])
def test_levels_are_cumulative_supersets(mode: str) -> None:
    prev: set[str] = set()
    for level in LEVELS:
        cur = set(rules_for(level, mode))  # type: ignore[arg-type]
        assert prev <= cur
        prev = cur


def test_merge_never_appears_below_full() -> None:
    for level in (Level.none, Level.assist, Level.confirm):
        for mode in ("local", "global"):
            assert "Bash(gh pr merge:*)" not in rules_for(level, mode)  # type: ignore[arg-type]


def test_rules_are_deduplicated_and_ordered() -> None:
    got = rules_for(Level.full, "global")
    assert len(got) == len(set(got))
    # spine before the code-publishing and irreversible tail
    assert got.index("Bash(git add:*)") < got.index("Bash(git push:*)")
    assert got.index("Bash(git push:*)") < got.index("Bash(gh pr merge:*)")


def test_settings_path_local_is_repo_settings_local(tmp_path: Path) -> None:
    assert settings_path(tmp_path, "local") == tmp_path / ".claude/settings.local.json"


def test_settings_path_global_is_home_settings() -> None:
    expected = Path.home() / ".claude/settings.json"
    assert settings_path(Path("/repo"), "global") == expected


def test_merge_adds_new_rules() -> None:
    result = merge_allow({}, ["Bash(git add:*)", "Bash(git commit:*)"])
    assert result.permissions["allow"] == ["Bash(git add:*)", "Bash(git commit:*)"]
    assert result.added == ["Bash(git add:*)", "Bash(git commit:*)"]
    assert result.already == []
    assert result.skipped == []


def test_merge_skips_denied_and_asked_rules() -> None:
    perms = {
        "allow": [],
        "deny": ["Bash(gh pr merge:*)"],
        "ask": ["Bash(git push:*)"],
    }
    result = merge_allow(perms, ["Bash(git push:*)", "Bash(gh pr merge:*)"])
    # A stricter existing policy wins: neither is promoted to allow.
    assert result.permissions["allow"] == []
    assert ("Bash(git push:*)", "already on ask") in result.skipped
    assert ("Bash(gh pr merge:*)", "already on deny") in result.skipped
    assert result.added == []


def test_merge_reports_already_allowed_as_noop() -> None:
    result = merge_allow({"allow": ["Bash(git add:*)"]}, ["Bash(git add:*)"])
    assert result.added == []
    assert result.already == ["Bash(git add:*)"]
    assert result.permissions["allow"] == ["Bash(git add:*)"]


def test_merge_does_not_mutate_input_and_preserves_keys() -> None:
    perms = {"allow": ["Bash(git add:*)"], "deny": ["Bash(rm -rf:*)"]}
    original = json.loads(json.dumps(perms))
    result = merge_allow(perms, ["Bash(git commit:*)"])
    # input untouched
    assert perms == original
    # deny carried through to the new block
    assert result.permissions["deny"] == ["Bash(rm -rf:*)"]
    assert "Bash(git commit:*)" in result.permissions["allow"]


def test_render_block_is_valid_permissions_json() -> None:
    rules = rules_for(Level.assist, "local")
    parsed = json.loads(render_block(rules))
    assert parsed == {"permissions": {"allow": rules}}
