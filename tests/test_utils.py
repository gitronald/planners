"""Tests for the pure helpers: split/parse frontmatter and the slug guard."""

from hypothesis import given
from hypothesis import strategies as st

from planners.utils import is_safe_slug, parse_frontmatter, split_frontmatter


def test_split_no_fence_is_lossless() -> None:
    text = "no fence here\nsecond line\n"
    assert split_frontmatter(text) == (None, text)


def test_split_lone_fence_has_no_closing() -> None:
    # An opening fence with no closing fence is treated as no frontmatter.
    text = "---\nstill open\n"
    assert split_frontmatter(text) == (None, text)


def test_split_basic() -> None:
    fm, body = split_frontmatter("---\na: b\n---\nbody\n")
    assert fm == "a: b\n"
    assert body == "body\n"


def test_split_crlf() -> None:
    fm, body = split_frontmatter("---\r\na: b\r\n---\r\nbody\r\n")
    assert fm == "a: b\r\n"
    assert body == "body\r\n"


def test_split_no_trailing_newline() -> None:
    fm, body = split_frontmatter("---\na: b\n---\nbody")
    assert fm == "a: b\n"
    assert body == "body"


def test_split_rule_in_body_uses_first_closing_fence() -> None:
    fm, body = split_frontmatter("---\na: b\n---\nx\n---\ny\n")
    assert fm == "a: b\n"
    assert body == "x\n---\ny\n"


@given(st.text())
def test_split_is_total_and_lossless_when_no_frontmatter(text: str) -> None:
    fm, body = split_frontmatter(text)
    if fm is None:
        assert body == text


def test_parse_empty_vs_null() -> None:
    parsed = parse_frontmatter("branch:\npr: null\nid: 5")
    assert parsed["branch"] == ""  # pending
    assert parsed["pr"] is None  # closed & N/A
    assert parsed["id"] == "5"


def test_parse_preserves_colons_in_value() -> None:
    parsed = parse_frontmatter("pr: https://github.com/o/r/pull/1")
    assert parsed["pr"] == "https://github.com/o/r/pull/1"


def test_parse_strips_quotes() -> None:
    assert parse_frontmatter('name: "quoted"')["name"] == "quoted"
    assert parse_frontmatter("name: 'quoted'")["name"] == "quoted"


def test_parse_skips_comments_and_blank_lines() -> None:
    parsed = parse_frontmatter("# a comment\n\nid: 1\n")
    assert parsed == {"id": "1"}


def test_is_safe_slug_accepts_kebab() -> None:
    assert is_safe_slug("ok-slug-123")
    assert is_safe_slug("plan")


def test_is_safe_slug_rejects_traversal_and_separators() -> None:
    assert not is_safe_slug("../etc")
    assert not is_safe_slug("a/b")
    assert not is_safe_slug("a\\b")
    assert not is_safe_slug("a\x00b")
    assert not is_safe_slug("UPPER")
    assert not is_safe_slug("a--b")
    assert not is_safe_slug("")
