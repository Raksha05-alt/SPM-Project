"""SCRUM-64 decisions: independent expected values from the story and interval rule."""

from datetime import datetime, time
from types import SimpleNamespace

import pytest

from apps.venues.matching import compare_venue, periods_overlap, satisfies_all


def dt(value):
    return datetime.fromisoformat(f"2027-03-01T{value}:00+08:00")


def venue(**changes):
    facts = dict(
        capacity=120,
        layouts=["THEATRE"],
        facilities=["Projector", "Hearing loop"],
        location="Central",
        wheelchair_access=True,
        is_active=True,
        opens_at=time(8),
        closes_at=time(20),
        operating_days=[0, 1, 2, 3, 4],
    )
    facts.update(changes)
    return SimpleNamespace(**facts)


@pytest.mark.parametrize("attendance, expected", [(119, True), (120, True), (121, False)])
def test_ac2_capacity_just_below_exactly_at_and_above(attendance, expected):
    assert satisfies_all(compare_venue(venue(), {"attendance": attendance})) is expected


@pytest.mark.parametrize(
    "facilities, expected",
    [(["projector"], True), (["Projector", "Hearing loop"], True), (["Projector", "Stage"], False)],
)
def test_ac1_every_required_facility_must_match(facilities, expected):
    assert satisfies_all(compare_venue(venue(), {"facilities": facilities})) is expected


def test_ac3_missing_layout_is_excluded_even_when_capacity_matches():
    assert not satisfies_all(compare_venue(venue(), {"attendance": 100, "layout": "BANQUET"}))


def test_ac4_empty_criteria_apply_only_operational_status():
    assert compare_venue(venue(), {}) == [{"criterion": "Operational status", "matches": True}]
    assert not satisfies_all(compare_venue(venue(is_active=False), {}))


def test_location_and_accessibility_filters_use_recorded_facts():
    assert satisfies_all(compare_venue(venue(), {"location": "CENT", "wheelchair_access": True}))
    assert not satisfies_all(
        compare_venue(venue(wheelchair_access=None), {"wheelchair_access": True})
    )
    assert not satisfies_all(compare_venue(venue(), {"location": "West"}))


@pytest.mark.parametrize(
    "start,end,expected",
    [("08:00", "20:00", True), ("07:59", "20:00", False), ("08:00", "20:01", False)],
)
def test_operating_hours_boundaries(start, end, expected):
    criteria = {"start": dt(start).isoformat(), "end": dt(end).isoformat()}
    assert satisfies_all(compare_venue(venue(), criteria)) is expected


def test_unknown_hours_closed_day_and_overnight_period_are_unavailable():
    criteria = {"start": dt("09:00").isoformat(), "end": dt("10:00").isoformat()}
    assert not satisfies_all(compare_venue(venue(opens_at=None), criteria))
    assert not satisfies_all(compare_venue(venue(operating_days=[6]), criteria))
    criteria["end"] = "2027-03-02T10:00:00+08:00"
    assert not satisfies_all(compare_venue(venue(), criteria))


@pytest.mark.parametrize(
    "first,last,expected",
    [
        ("08:00", "09:00", False),
        ("10:00", "11:00", False),
        ("08:00", "09:01", True),
        ("09:59", "11:00", True),
        ("09:00", "10:00", True),
    ],
)
def test_availability_adjacent_periods_do_not_overlap(first, last, expected):
    assert periods_overlap(dt("09:00"), dt("10:00"), dt(first), dt(last)) is expected


def test_timezones_are_compared_as_instants_in_singapore_operating_hours():
    criteria = {"start": "2027-03-01T01:00:00+00:00", "end": "2027-03-01T02:00:00+00:00"}
    assert satisfies_all(compare_venue(venue(), criteria))
    checks = compare_venue(venue(), criteria, [(dt("09:30"), dt("10:30"))])
    assert checks[-1] == {"criterion": "Availability", "matches": False}


@pytest.mark.parametrize("field", ["start", "end"])
def test_search_requires_both_period_endpoints(field):
    with pytest.raises(ValueError, match="both start and end"):
        compare_venue(venue(), {field: dt("09:00").isoformat()})


@pytest.mark.parametrize(
    "start,end",
    [
        ("2027-03-01T09:00:00", "2027-03-01T10:00:00+08:00"),
        ("2027-03-01T09:00:00+08:00", "2027-03-01T10:00:00"),
        ("not-a-date", "2027-03-01T10:00:00+08:00"),
        ("2027-03-01T09:00:00+08:00", "2027-03-01T09:00:00+08:00"),
        ("2027-03-01T10:00:00+08:00", "2027-03-01T09:00:00+08:00"),
    ],
)
def test_invalid_search_periods_are_not_treated_as_matching(start, end):
    with pytest.raises(ValueError):
        compare_venue(venue(), {"start": start, "end": end})


@pytest.mark.parametrize("occupied_end", ["09:00", "08:59"])
def test_empty_or_reversed_occupied_periods_are_rejected(occupied_end):
    with pytest.raises(ValueError, match="end after"):
        periods_overlap(dt("09:00"), dt("10:00"), dt("09:00"), dt(occupied_end))


@pytest.mark.parametrize("naive_endpoint", ["start", "end"])
def test_occupied_periods_cannot_depend_on_the_host_timezone(naive_endpoint):
    start, end = dt("09:00"), dt("10:00")
    if naive_endpoint == "start":
        start = start.replace(tzinfo=None)
    else:
        end = end.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        periods_overlap(dt("09:00"), dt("10:00"), start, end)


def test_ac1_a_failed_capacity_check_is_not_overridden_by_other_matches():
    checks = compare_venue(
        venue(), {"attendance": 121, "layout": "THEATRE", "facilities": ["Projector"]}
    )
    assert checks == [
        {"criterion": "Operational status", "matches": True},
        {"criterion": "Capacity", "matches": False},
        {"criterion": "Room layout", "matches": True},
        {"criterion": "Facilities", "matches": True},
    ]
    assert satisfies_all(checks) is False
