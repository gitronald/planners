"""Tree-wide convention guards from the plan's verification todos."""

from pathlib import Path

from planners.host import HOST
from planners.index import STATUS_ORDER
from planners.metadata import Status

_PACKAGE = Path(__file__).resolve().parent.parent / "planners"


def test_no_abandoned_anywhere_in_package_source() -> None:
    offenders: list[str] = []
    for path in _PACKAGE.rglob("*"):
        if path.suffix not in (".py", ".md"):
            continue
        if "abandoned" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(_PACKAGE)))
    assert offenders == [], f"'abandoned' must not appear; found in: {offenders}"


def test_no_abandoned_in_skill_bodies() -> None:
    for name, (_skill, source) in HOST.skill_sources().items():
        assert "abandoned" not in HOST.read(source), name


def test_status_enum_has_exactly_five_members_without_abandoned() -> None:
    assert [s.value for s in Status] == [
        "draft",
        "active",
        "done",
        "inactive",
        "retired",
    ]
    assert "abandoned" not in {s.value for s in Status}


def test_documented_status_order_matches_index_generator() -> None:
    # The index sort order, as documented in the plan and the index/backfill skills.
    assert STATUS_ORDER == [
        Status.active,
        Status.draft,
        Status.done,
        Status.inactive,
        Status.retired,
    ]
