"""Guards on the status enum and the order the index sorts it in."""

from planners.index import STATUS_ORDER
from planners.metadata import Status


def test_status_enum_has_exactly_seven_members() -> None:
    assert [s.value for s in Status] == [
        "draft",
        "active",
        "implemented",
        "blocked",
        "done",
        "inactive",
        "retired",
    ]


def test_documented_status_order_matches_index_generator() -> None:
    # The index sort order, as documented in the plan and the index/backfill skills.
    assert STATUS_ORDER == [
        Status.active,
        Status.implemented,
        Status.blocked,
        Status.draft,
        Status.done,
        Status.inactive,
        Status.retired,
    ]
