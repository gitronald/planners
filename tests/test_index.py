"""Tests for the index generator: table rendering, sort order, and full render."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from planners.index import (
    _format_instant,
    render_index,
    render_plans_table,
    sort_plans,
)
from planners.metadata import PlanMetadata, Status


def _meta(
    plan_id: int, status: Status, concluded: str = "", pr: str = "", title: str = "T"
) -> PlanMetadata:
    return PlanMetadata(
        id=plan_id,
        slug=f"plan-{plan_id}",
        status=status,
        branch="",
        created="2026-06-07T12:00:00-07:00",
        concluded=concluded,
        pr=pr,
        title=title,
        dirname=f"{plan_id:03d}-plan-{plan_id}",
    )


def test_render_table_curated_columns() -> None:
    table = render_plans_table(
        [_meta(7, Status.active, pr="https://github.com/o/r/pull/3")]
    )
    lines = table.splitlines()
    assert lines[0] == "| # | Plan | Status | Concluded | PR |"
    assert lines[1] == "|---|---|---|---|---|"
    expected = "| 007 | [T](plans/007-plan-7/plan.md) | active | — | [#3](https://github.com/o/r/pull/3) |"  # noqa: E501
    assert lines[2] == expected


def test_render_table_wide_columns() -> None:
    table = render_plans_table([_meta(1, Status.draft)], cols="all")
    assert (
        table.splitlines()[0]
        == "| # | Plan | Status | Branch | Created | Concluded | PR |"
    )


def test_sort_order_by_status_then_concluded_pr_id_desc() -> None:
    metas = [
        _meta(1, Status.retired, concluded="2026-01-01T00:00:00-07:00"),
        _meta(2, Status.draft),
        _meta(3, Status.done, concluded="2026-02-01T00:00:00-07:00"),
        _meta(4, Status.active),
        _meta(5, Status.inactive),
        _meta(6, Status.done, concluded="2026-03-01T00:00:00-07:00"),
    ]
    ordered = [m.id for m in sort_plans(metas)]
    # active, draft, then done (newest concluded first), inactive, retired
    assert ordered == [4, 2, 6, 3, 5, 1]


def test_sort_is_deterministic_total_order() -> None:
    metas = [_meta(i, Status.draft) for i in (3, 1, 2)]
    assert [m.id for m in sort_plans(metas)] == [3, 2, 1]


def _sub_meta(
    plan_id: int, sub: str, status: Status, concluded: str = "", title: str = "T"
) -> PlanMetadata:
    slug = f"plan-{plan_id}{sub}"
    return PlanMetadata(
        id=plan_id,
        slug=slug,
        status=status,
        branch="",
        created="2026-06-07T12:00:00-07:00",
        concluded=concluded,
        pr="",
        sub=sub,
        title=title,
        dirname=f"{plan_id:03d}{sub}-{slug}",
    )


def test_subplan_num_cell_and_link_include_letter() -> None:
    table = render_plans_table([_sub_meta(10, "a", Status.active, title="Step A")])
    row = table.splitlines()[2]
    assert row.startswith("| 010a | [Step A](plans/010a-plan-10a/plan.md) | active |")


def test_subplans_sort_by_own_status_not_grouped() -> None:
    umbrella = _meta(10, Status.active, title="U")
    sub_a = _sub_meta(10, "a", Status.done, concluded="2026-02-01T00:00:00-07:00")
    sub_b = _sub_meta(10, "b", Status.draft)
    other = _meta(5, Status.active, title="Other")  # another active, lower id
    # Each plan sorts by its OWN status: the active umbrella and the active
    # standalone lead (id desc), then the draft subplan, then the done subplan —
    # the subplans are not hoisted to the top under their active umbrella, so the
    # Status column stays monotonic.
    ordered = sort_plans([sub_b, other, sub_a, umbrella])
    assert [(m.id, m.sub) for m in ordered] == [
        (10, ""),  # active umbrella
        (5, ""),  # active standalone
        (10, "b"),  # draft subplan
        (10, "a"),  # done subplan
    ]


def test_umbrella_leads_subplans_when_keys_tie() -> None:
    # When an umbrella and its subplans share status/concluded/PR, the
    # (id desc, sub asc) tiebreakers keep them adjacent with the umbrella first.
    ts = "2026-02-01T00:00:00-07:00"
    umbrella = _meta(10, Status.done, concluded=ts, title="U")
    sub_a = _sub_meta(10, "a", Status.done, concluded=ts)
    sub_b = _sub_meta(10, "b", Status.done, concluded=ts)
    ordered = sort_plans([sub_b, sub_a, umbrella])
    assert [(m.id, m.sub) for m in ordered] == [(10, ""), (10, "a"), (10, "b")]


def test_subplan_sorts_on_own_keys() -> None:
    # A subplan sorts on its own status independently of any umbrella: a done
    # subplan sorts after an active plan.
    sub = _sub_meta(7, "a", Status.done, concluded="2026-02-01T00:00:00-07:00")
    active = _meta(3, Status.active)
    ordered = sort_plans([sub, active])
    assert [(m.id, m.sub) for m in ordered] == [(3, ""), (7, "a")]


def test_sort_concluded_orders_by_instant_not_lexical_string() -> None:
    # Plan 1 concluded at 18:00 UTC, plan 2 at 12:00 UTC. Lexically "10..." <
    # "12...", so a raw-string sort would put plan 2 first; by instant, plan 1
    # (later) must come first under the descending order.
    later = _meta(1, Status.done, concluded="2026-01-01T10:00:00-08:00")  # 18:00Z
    earlier = _meta(2, Status.done, concluded="2026-01-01T12:00:00+00:00")  # 12:00Z
    assert [m.id for m in sort_plans([earlier, later])] == [1, 2]


def test_render_table_escapes_pipes_in_title() -> None:
    table = render_plans_table([_meta(1, Status.active, title="a | b")])
    row = table.splitlines()[2]
    assert "[a \\| b]" in row
    # the escaped pipe must not introduce a spurious column: only unescaped
    # pipes are real delimiters (5 columns -> 6 delimiters)
    unescaped_pipes = row.count("|") - row.count("\\|")
    assert unescaped_pipes == 6


# --- render_index -------------------------------------------------------------


def test_render_index_emits_title_then_table() -> None:
    table = render_plans_table([_meta(1, Status.active)])
    out = render_index("Plans", table)
    assert out.startswith("# Plans\n\n")
    # the table body is embedded verbatim
    assert table in out
    # exactly one trailing newline (the table already supplies it)
    assert out.endswith("|\n")
    assert not out.endswith("\n\n")


def test_render_index_links_to_dir_plan_md() -> None:
    out = render_index("Plans", render_plans_table([_meta(1, Status.active)]))
    # links are relative to .planners/README.md: plans/{NNN}-{slug}/plan.md
    assert "[T](plans/001-plan-1/plan.md)" in out
    # no bare .md filename link (we link to the dir's plan.md)
    assert "001-plan-1.md)" not in out


def test_render_index_renders_empty_table() -> None:
    out = render_index("Plans", render_plans_table([]))
    assert out.startswith("# Plans\n\n| # | Plan | Status | Concluded | PR |\n")
    assert out.endswith("\n")


# --- timestamp formatting -----------------------------------------------------


def _tzdata_available() -> bool:
    try:
        ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:
        return False
    return True


_NEEDS_TZDATA = pytest.mark.skipif(
    not _tzdata_available(), reason="IANA tz database unavailable"
)


@_NEEDS_TZDATA
def test_format_instant_derives_us_acronym_from_saved_offset() -> None:
    # No normalization: the saved wall-clock time is shown as-is, and the saved
    # offset is matched against US zones at that instant to recover a catch-all
    # acronym — so the same offset reads differently across seasons.
    assert _format_instant("2026-06-08T14:52:26-07:00") == "2026-06-08 14:52 PT"
    assert _format_instant("2026-12-15T09:00:00-08:00") == "2026-12-15 09:00 PT"
    # -07:00 in December is Mountain standard, not Pacific daylight -> "MT"
    assert _format_instant("2026-12-15T09:00:00-07:00") == "2026-12-15 09:00 MT"
    assert _format_instant("2026-06-08T12:00:00-04:00") == "2026-06-08 12:00 ET"


def test_format_instant_utc_offset_fallback_and_empty() -> None:
    # UTC, a non-US offset, and the empty/unparseable cases don't need tz data.
    assert _format_instant("2026-06-08T12:00:00+00:00") == "2026-06-08 12:00 UTC"
    assert _format_instant("2026-06-08T12:00:00+05:30") == "2026-06-08 12:00 +05:30"
    assert _format_instant("") == "—"
    assert _format_instant(None) == "—"
    assert _format_instant("not-a-timestamp") == "not-a-timestamp"
