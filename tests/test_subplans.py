"""Tests for the nested-subplan transforms."""

import pytest

from planners.metadata import Status
from planners.subplans import (
    TABLE_END,
    TABLE_START,
    SubplanError,
    SubplanMetadata,
    check_set,
    is_subplan_filename,
    next_letter,
    phases,
    render_order,
    render_subplan,
    table_disagreements,
    write_table,
)


def _sub(
    letter: str,
    status: str = "draft",
    needs: tuple[str, ...] = (),
    title: str = "",
) -> SubplanMetadata:
    return SubplanMetadata(
        letter=letter,
        step=f"step-{letter}",
        status=Status(status),
        needs=needs,
        title=title,
        filename=f"{letter}-step-{letter}.md",
    )


def _umbrella(rows: str) -> str:
    return (
        "# Umbrella\n\n## Plan\n\n"
        f"{TABLE_START}\n"
        "| Subplan | Scope | Status | Note |\n"
        "|---|---|---|---|\n"
        f"{rows}"
        f"{TABLE_END}\n\n"
        "## Log\n"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a-investigate.md", True),
        ("b-the-work.md", True),
        ("ab-two-letters.md", False),
        ("A-upper.md", False),
        ("1-digit.md", False),
        ("b-.md", False),
        ("b-step.txt", False),
        ("notes.md", False),
    ],
)
def test_is_subplan_filename(name: str, expected: bool) -> None:
    assert is_subplan_filename(name) is expected


def test_from_text_reads_the_minimal_frontmatter() -> None:
    meta = SubplanMetadata.from_text(
        "---\nstatus: active\nbranch:\n---\n\n# Do the work\n", "b-work.md"
    )
    assert (meta.letter, meta.step, meta.status) == ("b", "work", Status.active)
    assert meta.branch == ""
    assert meta.pr == ""
    assert meta.needs == ()
    assert meta.title == "Do the work"
    assert meta.validate() == []


def test_from_text_reads_the_optional_keys() -> None:
    meta = SubplanMetadata.from_text(
        "---\nstatus: retired\nbranch: feature/x\npr: https://example.com/pull/3\n"
        "needs: [a, b]\nmoved_to: 015\n---\n",
        "c-step.md",
    )
    assert meta.branch == "feature/x"
    assert meta.pr == "https://example.com/pull/3"
    assert meta.needs == ("a", "b")
    assert meta.moved_to == "015"
    assert meta.validate() == []


@pytest.mark.parametrize(
    ("frontmatter", "expected"),
    [
        ("needs: a, b\n", ("a", "b")),
        ("needs: ['a', \"b\"]\n", ("a", "b")),
        ("needs: []\n", ()),
        ("needs:\n", ()),
        ("needs: null\n", ()),
        ("needs:\n  - a\n\n  - b\nbranch:\n  - c\n", ("a", "b")),
        ("# needs: a\n", ()),
    ],
)
def test_from_text_reads_needs_in_either_list_form(
    frontmatter: str, expected: tuple[str, ...]
) -> None:
    text = f"---\nstatus: draft\n{frontmatter}---\n"
    assert SubplanMetadata.from_text(text, "c-step.md").needs == expected


@pytest.mark.parametrize(
    ("text", "filename", "message"),
    [
        ("---\nstatus: draft\n---\n", "notes.md", "not <letter>-<step>.md"),
        ("# No frontmatter\n", "b-x.md", "missing YAML frontmatter"),
        ("---\nbranch:\n---\n", "b-x.md", "missing 'status'"),
        ("---\nstatus:\n---\n", "b-x.md", "missing 'status'"),
        ("---\nstatus: waiting\n---\n", "b-x.md", "invalid status"),
    ],
)
def test_from_text_raises_on_what_prevents_construction(
    text: str, filename: str, message: str
) -> None:
    with pytest.raises(SubplanError, match=message):
        SubplanMetadata.from_text(text, filename)


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("status: draft\nbranch: none\n", "literal string"),
        ("status: draft\npr: https://a/1 https://a/2\n", "single URL"),
        ("status: draft\nneeds: [ab]\n", "single letter"),
        ("status: draft\nneeds: [c]\n", "names the subplan itself"),
        ("status: draft\nneeds: [a, a]\n", "lists a letter twice"),
        ("status: retired\nmoved_to: later\n", "must be a plan number"),
        ("status: done\nmoved_to: 015\n", "closed as retired"),
    ],
)
def test_validate_reports_rule_violations(frontmatter: str, message: str) -> None:
    meta = SubplanMetadata.from_text(f"---\n{frontmatter}---\n", "c-step.md")
    assert any(message in error for error in meta.validate())


def test_moved_to_null_reads_as_unset() -> None:
    meta = SubplanMetadata.from_text(
        "---\nstatus: done\nmoved_to: null\n---\n", "c-s.md"
    )
    assert meta.moved_to == ""
    assert meta.validate() == []


def test_render_subplan_round_trips() -> None:
    text = render_subplan("Do the work", "The umbrella", "feature/x")
    meta = SubplanMetadata.from_text(text, "b-work.md")
    assert meta.status == Status.draft
    assert meta.branch == "feature/x"
    assert meta.title == "Do the work"
    assert "Part of [The umbrella](../plan.md)." in text
    assert "## Plan" in text and "## Log" in text


def test_render_subplan_without_a_branch_or_umbrella_title() -> None:
    text = render_subplan("Step", "")
    assert "\nbranch:\n" in text
    assert "Part of [the umbrella plan](../plan.md)." in text


def test_next_letter_starts_at_b_and_never_gives_a() -> None:
    assert next_letter([]) == "b"
    assert next_letter(["a"]) == "b"
    assert next_letter(["a", "b", "d"]) == "e"
    # Malformed entries do not count toward the maximum.
    assert next_letter(["", "zz", "c"]) == "d"


def test_next_letter_raises_when_exhausted() -> None:
    with pytest.raises(ValueError, match="exhausted"):
        next_letter(["z"])


def test_phases_group_independent_subplans() -> None:
    subs = [
        _sub("a"),
        _sub("b", needs=("a",)),
        _sub("c", needs=("a",)),
        _sub("d", needs=("a",)),
        _sub("e", needs=("b", "c", "d")),
    ]
    assert phases(subs) == [["a"], ["b", "c", "d"], ["e"]]
    assert render_order(phases(subs)) == "a -> (b, c, d) -> e"


def test_phases_ignore_a_need_with_no_subplan() -> None:
    assert phases([_sub("b", needs=("a",))]) == [["b"]]


def test_phases_raise_on_a_cycle() -> None:
    with pytest.raises(ValueError, match="cycle among: b, c"):
        phases([_sub("a"), _sub("b", needs=("c",)), _sub("c", needs=("b",))])


def test_check_set_reports_duplicates_missing_needs_and_cycles() -> None:
    twin = _sub("b")
    twin.filename = "b-other.md"
    errors = check_set(
        [
            _sub("b"),
            twin,
            _sub("c", needs=("x",)),
            _sub("d", needs=("e",)),
            _sub("e", needs=("d",)),
        ]
    )
    assert any("used by both b-step-b.md and b-other.md" in e for e in errors)
    assert any("needs 'x', which has no subplan" in e for e in errors)
    assert any("cycle" in e for e in errors)
    assert check_set([_sub("a"), _sub("b", needs=("a",))]) == []


def test_table_agrees_when_statuses_match() -> None:
    text = _umbrella(
        "| [a](subplans/a-step-a.md) | look | done | |\n"
        "| `b` | build | active | waiting on review |\n"
    )
    subs = [_sub("a", "done"), _sub("b", "active")]
    assert table_disagreements(text, subs) == []
    assert write_table(text, subs) == text


def test_table_disagreements_name_each_kind() -> None:
    text = _umbrella("| a | look | active | |\n| z | gone | done | |\n")
    problems = table_disagreements(text, [_sub("a", "done"), _sub("b")])
    assert "a: table says 'active', frontmatter says 'done'" in problems
    assert "b: no row in the table (b-step-b.md)" in problems
    assert "z: the table has a row with no subplan file" in problems


def test_table_disagreements_without_a_table() -> None:
    assert table_disagreements("# T\n", []) == []
    problems = table_disagreements("# T\n", [_sub("b")])
    assert len(problems) == 1 and "no subplan table" in problems[0]


def test_table_disagreements_without_a_status_column() -> None:
    text = f"{TABLE_START}\n| Subplan | Scope |\n|---|---|\n| b | x |\n{TABLE_END}\n"
    assert table_disagreements(text, [_sub("b")]) == [
        "the subplan table has no Status column"
    ]
    with pytest.raises(ValueError, match="no Status column"):
        write_table(text, [_sub("b")])


def test_table_with_empty_markers() -> None:
    text = f"## Plan\n\n{TABLE_START}\n{TABLE_END}\n"
    assert table_disagreements(text, []) == []
    assert table_disagreements(text, [_sub("b")]) == ["the subplan table is empty"]
    out = write_table(text, [_sub("b", title="Build it")])
    assert out == (
        f"## Plan\n\n{TABLE_START}\n"
        "| Subplan | Scope | Status | Note |\n"
        "|---|---|---|---|\n"
        "| [b](subplans/b-step-b.md) | Build it | draft |  |\n"
        f"{TABLE_END}\n"
    )


def test_write_table_changes_only_the_status_cell() -> None:
    text = _umbrella(
        "| a   | look at it      | active | a note \\| with a pipe |\n"
        "| b   | build   it      | draft  |   |\n"
    )
    out = write_table(text, [_sub("a", "done"), _sub("b", "draft")])
    assert "| a | look at it | done | a note \\| with a pipe |\n" in out
    # The row that was already right keeps its bytes, spacing included.
    assert "| b   | build   it      | draft  |   |\n" in out
    assert table_disagreements(out, [_sub("a", "done"), _sub("b", "draft")]) == []


def test_write_table_appends_a_missing_row_and_keeps_an_orphan() -> None:
    text = _umbrella("| z | by hand | done | keep me |\n")
    subs = [_sub("b", "active", title="Build | it")]
    out = write_table(text, subs)
    assert "| z | by hand | done | keep me |\n" in out
    assert (
        "| [b](subplans/b-step-b.md) | Build \\| it | active |  |\n"
        f"{TABLE_END}\n" in out
    )
    assert table_disagreements(out, subs) == [
        "z: the table has a row with no subplan file"
    ]


def test_write_table_follows_the_table_s_own_columns() -> None:
    text = (
        f"{TABLE_START}\n| Step | Status | Owner |\n|:--|:-:|--:|\n"
        f"| a | draft | someone |\n{TABLE_END}\n"
    )
    out = write_table(text, [_sub("a", "done"), _sub("b", "draft", title="T")])
    assert "| a | done | someone |\n" in out
    assert "| [b](subplans/b-step-b.md) | draft |  |\n" in out


def test_write_table_pads_a_short_row() -> None:
    text = _umbrella("| a | look |\n")
    out = write_table(text, [_sub("a", "done")])
    assert "| a | look | done |  |\n" in out


_FRESH_TABLE = (
    "### Subplans\n\n"
    f"{TABLE_START}\n"
    "| Subplan | Scope | Status | Note |\n"
    "|---|---|---|---|\n"
    "| [a](subplans/a-step-a.md) | Look | done |  |\n"
    "| [b](subplans/b-step-b.md) | Build | draft |  |\n"
    f"{TABLE_END}\n"
)
_FRESH_SUBS = [_sub("b", title="Build"), _sub("a", "done", title="Look")]


def test_write_table_creates_the_table_after_the_lead_paragraph() -> None:
    text = "# Umbrella\n\n## Plan\n\nThe goal.\n\n## Log\n\n- entry\n"
    out = write_table(text, _FRESH_SUBS)
    assert out == (
        f"# Umbrella\n\n## Plan\n\nThe goal.\n\n{_FRESH_TABLE}\n## Log\n\n- entry\n"
    )
    assert table_disagreements(out, _FRESH_SUBS) == []
    assert write_table(out, _FRESH_SUBS) == out


def test_write_table_creates_the_table_after_the_first_subsection() -> None:
    text = (
        "# Umbrella\n\n## Plan\n\n### Goal\n\nWhy.\n\n### Decided\n\n1. x\n\n"
        "## Log\n\n- entry\n"
    )
    out = write_table(text, _FRESH_SUBS)
    assert out == (
        f"# Umbrella\n\n## Plan\n\n### Goal\n\nWhy.\n\n{_FRESH_TABLE}\n"
        "### Decided\n\n1. x\n\n## Log\n\n- entry\n"
    )
    assert write_table(out, _FRESH_SUBS) == out


def test_write_table_without_a_spec_section_goes_before_the_log() -> None:
    text = "# Umbrella\n\nA line.\n\n## Log\n\n- entry\n"
    out = write_table(text, _FRESH_SUBS)
    assert out == f"# Umbrella\n\nA line.\n\n{_FRESH_TABLE}\n## Log\n\n- entry\n"


def test_write_table_leaves_an_existing_table_at_the_end_of_the_spec() -> None:
    text = (
        "## Plan\n\n### Goal\n\nWhy.\n\n### Subplans\n\n"
        f"{TABLE_START}\n| Subplan | Status |\n|---|---|\n| b | draft |\n{TABLE_END}\n"
        "\n## Log\n"
    )
    out = write_table(text, [_sub("b", "done")])
    assert out == text.replace("| b | draft |", "| b | done |")


def test_write_table_fills_a_marker_pair_placed_by_hand() -> None:
    text = f"## Plan\n\n{TABLE_START}\n{TABLE_END}\n\n### Goal\n\nWhy.\n"
    out = write_table(text, _FRESH_SUBS)
    assert out == (
        f"## Plan\n\n{TABLE_START}\n"
        "| Subplan | Scope | Status | Note |\n"
        "|---|---|---|---|\n"
        "| [a](subplans/a-step-a.md) | Look | done |  |\n"
        "| [b](subplans/b-step-b.md) | Build | draft |  |\n"
        f"{TABLE_END}\n\n### Goal\n\nWhy.\n"
    )


def test_write_table_without_subplans_or_a_table_is_a_no_op() -> None:
    assert write_table("# T\n", []) == "# T\n"


def test_markers_inside_a_code_fence_are_not_the_table() -> None:
    text = (
        "## Plan\n\n```\n"
        f"{TABLE_START}\n| Subplan | Status |\n|---|---|\n| b | done |\n{TABLE_END}\n"
        "```\n"
    )
    assert "no subplan table" in table_disagreements(text, [_sub("b")])[0]


def test_a_start_marker_with_no_end_is_not_a_table() -> None:
    text = f"{TABLE_START}\n| Subplan | Status |\n|---|---|\n| b | draft |\n"
    assert "no subplan table" in table_disagreements(text, [_sub("b")])[0]


def test_the_first_row_for_a_letter_is_the_one_kept_in_step() -> None:
    text = _umbrella("| b | one | draft | |\n| b | two | draft | |\n\nprose\n")
    out = write_table(text, [_sub("b", "done")])
    assert "| b | one | done |  |\n" in out
    assert "| b | two | draft | |\n" in out


def test_write_table_leaves_a_fenced_example_table_alone() -> None:
    example = "```\n| Sub | Status |\n|---|---|\n| b | draft |\n```\n"
    text = (
        f"{TABLE_START}\n{example}\n"
        "| Sub | Status |\n|---|---|\n| b | draft |\n"
        f"{TABLE_END}\n"
    )
    out = write_table(text, [_sub("b", "active")])
    assert example in out
    assert out.endswith(f"| b | active |\n{TABLE_END}\n")
