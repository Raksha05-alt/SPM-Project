"""Original SCRUM-64 ACs with real date-block and shared-layout integration."""

import datetime

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.venues.models import Venue, VenueBlock
from apps.venues.tests.conftest import make_venue

pytestmark = pytest.mark.django_db
SEARCH = "/api/venues/search/"
PERIOD = {"start": "2027-03-01T01:00:00Z", "end": "2027-03-01T09:00:00Z"}


def searchable_venue(**overrides):
    data = {
        "name": "Suitable room",
        "capacity": 60,
        "layouts": ["THEATRE"],
        "facilities": ["Projector", "Hearing loop"],
        "opens_at": datetime.time(8),
        "closes_at": datetime.time(22),
        "operating_days": [0, 1, 2, 3, 4],
    }
    data.update(overrides)
    return make_venue(**data)


def result_names(response):
    assert response.status_code == 200
    return [item["venue"]["name"] for item in response.data["results"]]


def test_ac1_supplied_filters_are_combined(signed_in_coordinator):
    searchable_venue()
    searchable_venue(name="Too small", capacity=59)
    searchable_venue(name="Wrong layout", layouts=["BANQUET"])
    searchable_venue(name="Missing a facility", facilities=["Projector"])
    searchable_venue(name="Closed", closes_at=datetime.time(16))
    searchable_venue(name="Out of service", in_service=False)

    response = signed_in_coordinator.get(
        SEARCH,
        {
            **PERIOD,
            "attendance": 60,
            "layout": "THEATRE",
            "facilities": ["projector", "Hearing loop"],
        },
    )

    assert result_names(response) == ["Suitable room"]
    assert response.data["availability_integrated"] is False
    assert response.data["date_blocks_integrated"] is True
    match = response.data["results"][0]
    assert match["availability_status"] == "UNVERIFIED"
    assert match["matches_recorded_requirements"] is True
    assert [check["key"] for check in match["criteria"] if check["result"] == "UNVERIFIED"] == [
        "booking_availability"
    ]


@pytest.mark.parametrize(
    "capacity,expected", [(59, []), (60, ["Suitable room"]), (61, ["Suitable room"])]
)
def test_ac2_capacity_boundary_includes_exact_capacity(signed_in_coordinator, capacity, expected):
    searchable_venue(capacity=capacity)
    assert result_names(signed_in_coordinator.get(SEARCH, {"attendance": 60})) == expected


def test_ac3_unsupported_layout_is_excluded(signed_in_coordinator):
    searchable_venue(layouts=["CLASSROOM"])
    assert result_names(signed_in_coordinator.get(SEARCH, {"layout": "THEATRE"})) == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"attendance": ""},
        {"layout": ""},
        {"start": "", "end": ""},
        {"facilities": ""},
        {"facilities": ["", "  "]},
    ],
)
def test_ac4_omitted_or_empty_filters_do_not_exclude_on_that_basis(signed_in_coordinator, params):
    searchable_venue(capacity=1, layouts=[], facilities=[], opens_at=None, closes_at=None)
    assert result_names(signed_in_coordinator.get(SEARCH, params)) == ["Suitable room"]


def test_ac4_other_filters_still_apply_when_layout_and_period_are_omitted(signed_in_coordinator):
    searchable_venue(name="Enough space", capacity=60, layouts=[])
    searchable_venue(name="Too small", capacity=59)
    assert result_names(signed_in_coordinator.get(SEARCH, {"attendance": 60})) == ["Enough space"]


def test_ac5_no_matches_returns_an_empty_result_not_a_server_error(signed_in_coordinator):
    searchable_venue()
    response = signed_in_coordinator.get(SEARCH, {"attendance": 1000})
    assert result_names(response) == []
    assert response.data["limitation"]


@pytest.mark.parametrize("fixture_name", ["organiser", "attendee", "venue_staff", "tech_staff"])
def test_ac6_only_coordinators_can_search(api, request, fixture_name):
    user = request.getfixturevalue(fixture_name)
    api.force_authenticate(user)
    response = api.get(SEARCH)
    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=user, action=f"GET {SEARCH}", allowed=False).exists()


def test_anonymous_search_is_refused_and_audited(api):
    assert api.get(SEARCH).status_code == 403
    assert AuditLog.objects.filter(actor=None, action=f"GET {SEARCH}", allowed=False).exists()


@pytest.mark.parametrize(
    "params",
    [
        {"attendance": 0},
        {"attendance": -1},
        {"attendance": "many"},
        {"layout": "IGLOO"},
        {"start": "invalid", "end": PERIOD["end"]},
        {"start": PERIOD["start"]},
        {"end": PERIOD["end"]},
        {"start": PERIOD["end"], "end": PERIOD["start"]},
        {"start": PERIOD["start"], "end": PERIOD["start"]},
    ],
)
def test_invalid_filters_return_validation_errors_without_mutation(signed_in_coordinator, params):
    searchable_venue()
    assert signed_in_coordinator.get(SEARCH, params).status_code == 400
    assert Venue.objects.count() == 1


def test_facility_names_are_trimmed_case_insensitive_and_all_required(signed_in_coordinator):
    searchable_venue()
    response = signed_in_coordinator.get(
        SEARCH, {"facilities": [" projector ", "PROJECTOR", "hearing loop"]}
    )
    assert result_names(response) == ["Suitable room"]
    assert response.data["criteria"]["facilities"] == ["projector", "hearing loop"]
    assert (
        result_names(signed_in_coordinator.get(SEARCH, {"facilities": ["Projector", "Stage"]}))
        == []
    )


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("2027-03-01T00:00:00Z", "2027-03-01T14:00:00Z", True),
        ("2027-02-28T23:59:00Z", "2027-03-01T14:00:00Z", False),
        ("2027-03-01T00:00:00Z", "2027-03-01T14:01:00Z", False),
        ("2027-03-06T01:00:00Z", "2027-03-06T09:00:00Z", False),
        ("2027-03-01T01:00:00Z", "2027-03-02T09:00:00Z", False),
    ],
)
def test_event_period_uses_singapore_operating_days_and_exact_hour_boundaries(
    signed_in_coordinator, start, end, expected
):
    searchable_venue()
    names = result_names(signed_in_coordinator.get(SEARCH, {"start": start, "end": end}))
    assert bool(names) is expected


def test_missing_hours_cannot_establish_a_match_for_a_supplied_period(signed_in_coordinator):
    searchable_venue(opens_at=None, closes_at=None)
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == []


def test_search_queries_do_not_grow_per_venue(signed_in_coordinator, django_assert_num_queries):
    for index in range(5):
        searchable_venue(name=f"Room {index}")
    # SCRUM-91: +1 constant query for the layout catalogue's current names (AC2).
    with django_assert_num_queries(3):
        response = signed_in_coordinator.get(SEARCH)
    assert len(response.data["results"]) == 5


@pytest.mark.parametrize(
    "start,end,visible",
    [
        ("2027-03-01T00:00:00Z", "2027-03-01T01:00:00Z", True),
        ("2027-03-01T09:00:00Z", "2027-03-01T10:00:00Z", True),
        ("2027-03-01T00:59:59Z", "2027-03-01T01:00:01Z", False),
        ("2027-03-01T08:59:59Z", "2027-03-01T09:00:01Z", False),
        ("2027-03-01T01:00:00Z", "2027-03-01T09:00:00Z", False),
        ("2027-03-01T02:00:00Z", "2027-03-01T03:00:00Z", False),
        ("2027-02-28T01:00:00Z", "2027-02-28T09:00:00Z", True),
    ],
)
def test_ac1_real_blocks_exclude_overlaps_but_not_adjacent_or_other_dates(
    signed_in_coordinator, start, end, visible
):
    venue = searchable_venue()
    VenueBlock.objects.create(venue=venue, reason="Maintenance", starts_at=start, ends_at=end)
    response = signed_in_coordinator.get(SEARCH, PERIOD)
    assert result_names(response) == ([venue.name] if visible else [])


def test_ac1_staff_block_create_edit_and_remove_refresh_search_results(
    signed_in_coordinator, venue_staff
):
    venue = searchable_venue()
    staff = APIClient()
    staff.force_authenticate(venue_staff)
    blocks = f"/api/venues/{venue.pk}/blocks/"
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == [venue.name]
    response = staff.post(
        blocks,
        {"reason": "Safety inspection", "starts_at": PERIOD["start"], "ends_at": PERIOD["end"]},
        format="json",
    )
    assert response.status_code == 201
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == []
    item = f"{blocks}{response.data['id']}/"
    assert (
        staff.patch(
            item,
            {"starts_at": "2027-03-02T01:00:00Z", "ends_at": "2027-03-02T09:00:00Z"},
            format="json",
        ).status_code
        == 200
    )
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == [venue.name]
    assert (
        staff.patch(
            item, {"starts_at": PERIOD["start"], "ends_at": PERIOD["end"]}, format="json"
        ).status_code
        == 200
    )
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == []
    assert staff.delete(item).status_code == 204
    assert result_names(signed_in_coordinator.get(SEARCH, PERIOD)) == [venue.name]


def test_ac4_no_period_does_not_apply_temporal_filter_even_if_venue_is_currently_blocked(
    signed_in_coordinator, monkeypatch
):
    venue = searchable_venue(opens_at=None, closes_at=None)
    now = parse_datetime("2027-03-01T01:00:00Z")
    monkeypatch.setattr(timezone, "now", lambda: now)
    VenueBlock.objects.create(
        venue=venue,
        reason="Current maintenance",
        starts_at=now,
        ends_at=now + datetime.timedelta(hours=1),
    )
    response = signed_in_coordinator.get(SEARCH)
    assert result_names(response) == [venue.name]
    assert response.data["results"][0]["venue"]["operational_status"] == "Blocked"
    assert "date_blocks" not in [c["key"] for c in response.data["results"][0]["criteria"]]


def test_ac1_block_search_uses_constant_queries_with_multiple_real_blocks(
    signed_in_coordinator, django_assert_num_queries
):
    for i in range(5):
        venue = searchable_venue(name=f"Room {i}")
        VenueBlock.objects.create(
            venue=venue, reason="Maintenance", starts_at=PERIOD["start"], ends_at=PERIOD["end"]
        )
    with django_assert_num_queries(2):
        response = signed_in_coordinator.get(SEARCH, PERIOD)
    assert result_names(response) == []
