"""Tests for the pure body-editing helpers."""

from planners.body import (
    append_to_section,
    fenced_lines,
    insert_after_first_subsection,
    insert_before_section,
    section_span,
    set_frontmatter_key,
)

_PLAN = (
    "---\nstatus: draft\nbranch:\n---\n\n# Title\n\n## Plan\n\nThe spec.\n\n"
    "## Log\n\n- first\n\n## Retrospective\n\n- insight\n"
)


def test_fenced_lines_marks_the_fence_and_its_contents() -> None:
    lines = ["a\n", "```\n", "## Log\n", "```\n", "b\n"]
    assert fenced_lines(lines) == [False, True, True, True, False]


def test_fenced_lines_longer_fence_quotes_a_shorter_one() -> None:
    lines = ["````md\n", "```\n", "x\n", "```\n", "````\n", "after\n"]
    assert fenced_lines(lines) == [True, True, True, True, True, False]


def test_fenced_lines_unclosed_fence_runs_to_the_end() -> None:
    assert fenced_lines(["~~~\n", "x\n", "```\n"]) == [True, True, True]


def test_section_span_ends_at_the_next_heading_of_the_same_level() -> None:
    lines = _PLAN.splitlines(keepends=True)
    span = section_span(_PLAN, "Log")
    assert span is not None
    start, end = span
    assert lines[start] == "## Log\n"
    assert lines[end] == "## Retrospective\n"


def test_section_span_runs_to_the_end_for_the_last_section() -> None:
    span = section_span(_PLAN, "Retrospective")
    assert span is not None
    assert span[1] == len(_PLAN.splitlines())


def test_section_span_skips_subheadings_and_matches_whole_titles() -> None:
    text = "## Log\n\n### Detail\n\nx\n\n## Logistics\n"
    span = section_span(text, "Log")
    assert span == (0, 6)
    assert section_span(text, "Logistic") is None


def test_section_span_ignores_a_heading_inside_a_code_fence() -> None:
    text = "## Plan\n\n```\n## Log\n```\n\n## Log\n\n- real\n"
    span = section_span(text, "Log")
    assert span == (6, 9)


def test_append_to_section_adds_the_entry_before_the_next_section() -> None:
    out = append_to_section(_PLAN, "Log", "- second")
    assert "- first\n- second\n\n## Retrospective" in out
    # Nothing else moved.
    assert out.replace("- second\n", "") == _PLAN


def test_append_to_section_fills_an_empty_section() -> None:
    out = append_to_section("# T\n\n## Log\n", "Log", "- only")
    assert out == "# T\n\n## Log\n\n- only\n"


def test_append_to_section_handles_a_missing_final_newline() -> None:
    out = append_to_section("## Log\n\n- first", "Log", "- second")
    assert out == "## Log\n\n- first\n- second\n"


def test_append_to_section_creates_the_section_before_a_named_one() -> None:
    text = "# T\n\n## Plan\n\nSpec.\n\n## Retrospective\n\n- insight\n"
    out = append_to_section(text, "Log", "- entry", before=("Handoff", "Retrospective"))
    assert out == (
        "# T\n\n## Plan\n\nSpec.\n\n## Log\n\n- entry\n\n"
        "## Retrospective\n\n- insight\n"
    )


def test_append_to_section_creates_the_section_at_the_end() -> None:
    assert append_to_section("# T\n", "Log", "- entry") == "# T\n\n## Log\n\n- entry\n"
    assert append_to_section("# T", "Log", "- entry") == "# T\n\n## Log\n\n- entry\n"
    assert append_to_section("", "Log", "- entry") == "## Log\n\n- entry\n"


def test_insert_before_section_picks_the_earliest_named_section() -> None:
    out = insert_before_section(_PLAN, "### New\n\nbody", ("Retrospective", "Log"))
    assert "The spec.\n\n### New\n\nbody\n\n## Log" in out


def test_insert_before_section_at_the_top_of_the_text() -> None:
    assert insert_before_section("## Log\n", "intro", ("Log",)) == "intro\n\n## Log\n"


def test_insert_after_first_subsection_lands_between_subsections() -> None:
    text = (
        "## Plan\n\n### Goal\n\nWhy.\n\n#### Detail\n\nMore.\n\n### Decided\n\n1. x\n"
    )
    out = insert_after_first_subsection(text, "### New\n\nbody", "Plan")
    assert out == (
        "## Plan\n\n### Goal\n\nWhy.\n\n#### Detail\n\nMore.\n\n"
        "### New\n\nbody\n\n### Decided\n\n1. x\n"
    )


def test_insert_after_first_subsection_follows_the_lead_paragraph() -> None:
    out = insert_after_first_subsection(_PLAN, "### New\n\nbody", "Plan")
    assert "## Plan\n\nThe spec.\n\n### New\n\nbody\n\n## Log\n" in out


def test_insert_after_first_subsection_into_an_empty_section() -> None:
    out = insert_after_first_subsection("## Plan\n\n## Log\n", "body", "Plan")
    assert out == "## Plan\n\nbody\n\n## Log\n"


def test_insert_after_first_subsection_at_the_end_of_the_text() -> None:
    out = insert_after_first_subsection("## Plan\n\n### Goal\n\nWhy.", "body", "Plan")
    assert out == "## Plan\n\n### Goal\n\nWhy.\n\nbody\n"


def test_insert_after_first_subsection_falls_back_before_a_named_section() -> None:
    out = insert_after_first_subsection("# T\n\n## Log\n", "body", "Plan", ("Log",))
    assert out == "# T\n\nbody\n\n## Log\n"


def test_set_frontmatter_key_replaces_a_line_where_it_stands() -> None:
    out = set_frontmatter_key(_PLAN, "status", "active")
    assert out.startswith("---\nstatus: active\nbranch:\n---\n")
    assert out.replace("status: active", "status: draft") == _PLAN


def test_set_frontmatter_key_appends_a_new_key_and_keeps_the_others() -> None:
    text = "---\nstatus: retired\nneeds: [a]\n# note: x\n---\n\n# T\n"
    out = set_frontmatter_key(text, "moved_to", "015")
    assert (
        out
        == "---\nstatus: retired\nneeds: [a]\n# note: x\nmoved_to: 015\n---\n\n# T\n"
    )


def test_set_frontmatter_key_renders_empty_and_null() -> None:
    assert set_frontmatter_key(_PLAN, "branch", None).startswith(
        "---\nstatus: draft\nbranch: null\n---\n"
    )
    assert set_frontmatter_key(_PLAN, "status", "").startswith("---\nstatus:\n")


def test_set_frontmatter_key_does_not_edit_a_commented_line() -> None:
    text = "---\n# status: old\nstatus: draft\n---\n"
    assert set_frontmatter_key(text, "status", "done") == (
        "---\n# status: old\nstatus: done\n---\n"
    )


def test_set_frontmatter_key_adds_a_block_when_there_is_none() -> None:
    assert set_frontmatter_key("# T\n", "status", "draft") == (
        "---\nstatus: draft\n---\n\n# T\n"
    )
    assert set_frontmatter_key("", "status", "draft") == "---\nstatus: draft\n---\n"
    # An opening fence that never closes is not frontmatter.
    assert set_frontmatter_key("---\nstatus: x\n", "status", "draft") == (
        "---\nstatus: draft\n---\n\n---\nstatus: x\n"
    )


def test_a_title_that_ends_in_a_hash_keeps_it() -> None:
    # The closing run of `#` is set off by whitespace, as CommonMark has it. It
    # used to be stripped without one, so `## Log#` was read as the Log section.
    text = "## Log#\n\n- not the log\n\n## C#\n\n- notes\n\n## Log ##\n\n- real\n"
    assert section_span(text, "Log") == (8, 11)
    assert section_span(text, "Log#") == (0, 4)
    assert section_span(text, "C#") == (4, 8)


def test_a_heading_with_tabs_and_trailing_space_is_read() -> None:
    assert section_span("##\tLog \t\n\n- x\n", "Log") == (0, 3)
    assert section_span("## Log #  \n", "Log") == (0, 1)
    # No space after the opening run is not a heading.
    assert section_span("##Log\n", "Log") is None


def test_set_frontmatter_key_drops_a_duplicate_the_parser_would_read() -> None:
    # The parser keeps the last of two lines; a write that replaced only the first
    # would leave the old value in force.
    text = "---\nstatus: draft\nslug: x\nstatus: active\n---\n\n# T\n"
    assert set_frontmatter_key(text, "status", "done") == (
        "---\nstatus: done\nslug: x\n---\n\n# T\n"
    )
