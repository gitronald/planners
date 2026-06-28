"""Tests for the PlanMetadata schema: parse, render, validate, and round-trip."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from planners.metadata import (
    DIRNAME_RE,
    PlanError,
    PlanMetadata,
    Status,
    extract_title,
    is_plan_dirname,
    next_number,
    next_sub,
)
from planners.utils import is_safe_slug

# --- strategies for the round-trip property ----------------------------------

_VALUE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/:. "


def _is_clean_value(s: str) -> bool:
    return s == s.strip() and s != "" and s.lower() not in ("null", "none")


_nonempty_value = st.text(alphabet=_VALUE_ALPHABET, min_size=1, max_size=24).filter(
    _is_clean_value
)
# branch/concluded/pr: "" (pending), None (closed & N/A), or a plain value
_nullable_value = st.one_of(st.just(""), st.none(), _nonempty_value)
_slugs = st.from_regex(r"[a-z0-9]+(?:-[a-z0-9]+)*", fullmatch=True).filter(
    lambda s: len(s) <= 30 and is_safe_slug(s)
)
# sub: "" (ordinary/umbrella) or a single subplan letter
_subs = st.sampled_from(["", "a", "b", "m", "z"])
_titles = (
    st.text(alphabet=_VALUE_ALPHABET + "#", min_size=0, max_size=24)
    .map(str.strip)
    .filter(lambda s: "\n" not in s)
)


@st.composite
def _plan_metadata(draw: st.DrawFn) -> PlanMetadata:
    return PlanMetadata(
        id=draw(st.integers(min_value=0, max_value=999)),
        slug=draw(_slugs),
        status=draw(st.sampled_from(list(Status))),
        branch=draw(_nullable_value),
        created=draw(st.one_of(st.just(""), _nonempty_value)),
        concluded=draw(_nullable_value),
        pr=draw(_nullable_value),
        sub=draw(_subs),
        title=draw(_titles),
        dirname=None,
    )


# --- round-trip + golden ------------------------------------------------------


@given(_plan_metadata())
def test_render_then_from_text_round_trips(meta: PlanMetadata) -> None:
    assert PlanMetadata.from_text(meta.render()) == meta


def test_render_golden_string() -> None:
    meta = PlanMetadata(
        id=7,
        slug="add-thing",
        status=Status.active,
        branch="feature/add-thing",
        created="2026-06-07T12:00:00-07:00",
        concluded="",
        pr="https://github.com/o/r/pull/3",
        title="Add a thing",
    )
    assert meta.render() == (
        "---\n"
        "id: 7\n"
        "slug: add-thing\n"
        "status: active\n"
        "branch: feature/add-thing\n"
        "created: 2026-06-07T12:00:00-07:00\n"
        "concluded:\n"
        "pr: https://github.com/o/r/pull/3\n"
        "---\n"
        "\n"
        "# Add a thing\n"
    )


def test_render_uses_null_token_for_closed_na_fields() -> None:
    meta = PlanMetadata(
        id=1,
        slug="x",
        status=Status.done,
        branch=None,
        created="2026-06-07T12:00:00-07:00",
        concluded="2026-06-08T09:00:00-07:00",
        pr=None,
        title="X",
    )
    assert "branch: null" in meta.render()
    assert "pr: null" in meta.render()


# --- extract_title ------------------------------------------------------------


def test_extract_title_first_h1() -> None:
    assert extract_title("\n# The Title\n\n## Sub\n") == "The Title"


def test_extract_title_empty_heading() -> None:
    assert extract_title("# \n") == ""
    assert extract_title("no heading\n") == ""


# --- from_text structural failures -------------------------------------------


def test_from_text_requires_frontmatter() -> None:
    with pytest.raises(PlanError, match="frontmatter"):
        PlanMetadata.from_text("no frontmatter here\n")


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("---\nslug: x\nstatus: draft\n---\n# t\n", "id"),
        ("---\nid: notint\nslug: x\nstatus: draft\n---\n# t\n", "non-integer"),
        ("---\nid: 1\nstatus: draft\n---\n# t\n", "slug"),
        ("---\nid: 1\nslug: x\n---\n# t\n", "status"),
        ("---\nid: 1\nslug: x\nstatus: Active\n---\n# t\n", "invalid status"),
        ("---\nid: 1\nslug: x\nstatus: abandoned\n---\n# t\n", "invalid status"),
    ],
)
def test_from_text_structural_errors(text: str, match: str) -> None:
    with pytest.raises(PlanError, match=match):
        PlanMetadata.from_text(text)


# --- validate -----------------------------------------------------------------


def _valid_active() -> PlanMetadata:
    return PlanMetadata(
        id=7,
        slug="add-thing",
        status=Status.active,
        branch="feature/add-thing",
        created="2026-06-07T12:00:00-07:00",
        concluded="",
        pr="https://github.com/o/r/pull/3",
        title="Add a thing",
        dirname="007-add-thing",
    )


def test_validate_clean_plan() -> None:
    assert _valid_active().validate() == []


def test_validate_id_slug_must_match_dirname() -> None:
    meta = _valid_active()
    meta.dirname = "001-other"
    errors = meta.validate()
    assert any("id 7 != directory prefix 1" in e for e in errors)
    assert any("slug 'add-thing' != directory slug 'other'" in e for e in errors)


def test_validate_empty_dirname_skips_identity_check() -> None:
    # A path with no parent component yields dirname="" (e.g. from_file("plan.md"));
    # with no directory context there is nothing to check against, so it must not
    # be flagged as "directory '' is not NNN-slug".
    meta = _valid_active()
    meta.dirname = ""
    assert meta.validate() == []


def test_validate_rejects_literal_none() -> None:
    meta = _valid_active()
    meta.pr = "none"
    assert any("literal string 'none'" in e for e in meta.validate())


def test_validate_concluded_must_be_empty_on_open_plan() -> None:
    meta = _valid_active()
    meta.status = Status.draft
    meta.concluded = "2026-06-08T09:00:00-07:00"
    assert any("must leave concluded empty" in e for e in meta.validate())


def test_validate_no_null_on_open_plan() -> None:
    meta = _valid_active()
    meta.pr = None
    assert any("must not use null for pr" in e for e in meta.validate())


def test_validate_done_requires_concluded() -> None:
    meta = _valid_active()
    meta.status = Status.done
    meta.concluded = ""
    assert any("requires a concluded timestamp" in e for e in meta.validate())


def test_validate_retired_requires_concluded() -> None:
    # retired is the other CLOSED_STATUS; it goes through the same branch as
    # done and must also require a concluded timestamp.
    meta = _valid_active()
    meta.status = Status.retired
    meta.concluded = ""
    assert any("requires a concluded timestamp" in e for e in meta.validate())


def test_old_completed_key_parses_empty_and_fails_validate() -> None:
    # Hard cutover: there is no read-alias. Frontmatter that still uses the old
    # `completed:` key (no `concluded:`) parses with an empty concluded, so a
    # terminal plan fails validation rather than silently picking up the old
    # value. This locks in the accepted "fine for it to fail" behavior and guards
    # against a fallback being reintroduced.
    text = (
        "---\n"
        "id: 1\n"
        "slug: x\n"
        "status: done\n"
        "branch: null\n"
        "created: 2026-06-07T12:00:00-07:00\n"
        "completed: 2026-06-08T09:00:00-07:00\n"
        "pr: null\n"
        "---\n"
        "\n"
        "# X\n"
    )
    meta = PlanMetadata.from_text(text)
    assert meta.concluded == ""
    assert any("requires a concluded timestamp" in e for e in meta.validate())


def test_validate_unparseable_timestamp() -> None:
    meta = _valid_active()
    meta.created = "not-a-date"
    assert any("not ISO-8601" in e for e in meta.validate())


def test_validate_inactive_keeps_fields_empty() -> None:
    meta = PlanMetadata(
        id=2,
        slug="parked",
        status=Status.inactive,
        branch="",
        created="2026-06-07T12:00:00-07:00",
        concluded="",
        pr="",
        title="Parked",
        dirname="002-parked",
    )
    assert meta.validate() == []


# --- is_plan_dirname ----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("000-initial", True),
        ("001-planners-storage-layout", True),
        ("12-multi-word-slug", True),
        ("plan.md", False),  # a file, not a plan dir
        ("README.md", False),
        ("notes", False),  # no NNN- prefix
        ("abc-thing", False),  # prefix is not digits
    ],
)
def test_is_plan_dirname(name: str, ok: bool) -> None:
    assert is_plan_dirname(name) is ok


# --- next_number --------------------------------------------------------------


@pytest.mark.parametrize(
    ("ids", "expected"),
    [([], 0), ([0], 1), ([0, 3, 1], 4), ([5], 6)],
)
def test_next_number(ids: list[int], expected: int) -> None:
    assert next_number(ids) == expected


def test_next_number_ignores_duplicate_subplan_ids() -> None:
    # An umbrella 10 plus its subplans all carry id 10; the next top-level number
    # is still 11, not affected by the duplicates.
    assert next_number([0, 10, 10, 10]) == 11


# --- subplans: identity, render, next_sub -------------------------------------


@pytest.mark.parametrize(
    ("dirname", "groups"),
    [
        ("010-umbrella", ("010", "", "umbrella")),
        ("010a-step-one", ("010", "a", "step-one")),
        ("12-multi-word-slug", ("12", "", "multi-word-slug")),
        ("010ab-bad", ("010", "ab", "bad")),  # multi-letter: parsed, not skipped
    ],
)
def test_dirname_re_splits_id_sub_slug(
    dirname: str, groups: tuple[str, str, str]
) -> None:
    match = DIRNAME_RE.match(dirname)
    assert match is not None
    assert match.groups() == groups


def test_is_plan_dirname_accepts_subplan_suffix() -> None:
    assert is_plan_dirname("010a-step-one")
    assert is_plan_dirname("010ab-bad")  # malformed but still discovered


def _valid_subplan() -> PlanMetadata:
    meta = _valid_active()
    meta.id = 10
    meta.sub = "a"
    meta.dirname = "010a-add-thing"  # slug add-thing from _valid_active
    return meta


def test_validate_clean_subplan() -> None:
    assert _valid_subplan().validate() == []


def test_validate_subplan_letter_must_match_dirname() -> None:
    meta = _valid_subplan()
    meta.sub = "b"  # dir says 'a'
    assert any("sub 'b' != directory sub 'a'" in e for e in meta.validate())


def test_validate_rejects_multiletter_sub() -> None:
    meta = _valid_subplan()
    meta.sub = "ab"
    meta.dirname = "010ab-add-thing"  # keep identity matching so only the rule fires
    assert any("must be a single letter" in e for e in meta.validate())


def test_render_emits_sub_after_slug_for_subplan() -> None:
    out = _valid_subplan().render()
    assert "\nslug: add-thing\nsub: a\nstatus: active\n" in out


def test_render_omits_sub_for_ordinary_plan() -> None:
    assert "sub:" not in _valid_active().render()


@pytest.mark.parametrize(
    ("subs", "expected"),
    [([], "a"), ([""], "a"), (["", "a"], "b"), (["a", "b", ""], "c"), (["c"], "d")],
)
def test_next_sub(subs: list[str], expected: str) -> None:
    assert next_sub(subs) == expected


def test_next_sub_ignores_malformed_multiletter_subs() -> None:
    # A corrupt 'sub: ab' must not reach ord() (which rejects length-2 strings);
    # it is skipped, and the next free single letter is returned.
    assert next_sub(["", "a", "ab"]) == "b"
    assert next_sub(["ab"]) == "a"


def test_next_sub_raises_when_letters_exhausted() -> None:
    # Past 'z' there is no letter; raise rather than emit '{' (which later
    # directory scans would silently drop).
    with pytest.raises(ValueError, match="exhausted"):
        next_sub(["z"])
