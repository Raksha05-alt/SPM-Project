"""SCRUM-64 (US-10.1) - filter venues against event requirements."""

from datetime import time

import pytest

from apps.core.statuses import EventStatus
from apps.venues.tests.helpers import book, iso
from conftest import future_at, make_event, make_venue

SEARCH = "/api/venues/search/"


def names(response):
    return [row["name"] for row in response.data["results"]]


@pytest.fixture
def catalogue(db):
    return {
        "hall": make_venue(
            name="Grand Hall",
            capacity=300,
            layouts=["THEATRE", "BANQUET"],
            facilities=["Projector", "Video conferencing", "Stage"],
            location="Marina Building",
        ),
        "room": make_venue(
            name="Meeting Room",
            capacity=20,
            layouts=["BOARDROOM"],
            facilities=["Video conferencing"],
            location="Tower One",
            wheelchair_access=False,
        ),
        "studio": make_venue(
            name="Studio",
            capacity=120,
            layouts=["CLASSROOM", "THEATRE"],
            facilities=["Projector"],
            location="Marina Building",
            opens_at=time(9, 0),
            closes_at=time(17, 0),
        ),
    }


@pytest.mark.django_db
def test_ac1_only_venues_satisfying_every_criterion_are_listed(signed_in_coordinator, catalogue):
    response = signed_in_coordinator.get(
        SEARCH,
        {
            "start": iso(future_at(6, 10)),
            "end": iso(future_at(6, 12)),
            "attendance": 100,
            "layout": "THEATRE",
            "facilities": "Projector, video conferencing",
        },
    )

    assert response.status_code == 200
    assert names(response) == ["Grand Hall"]
    checks = {c["criterion"]: c["matches"] for c in response.data["results"][0]["checks"]}
    assert checks == {
        "Operational status": True,
        "Capacity": True,
        "Room layout": True,
        "Facilities": True,
        "Operating hours": True,
        "Availability": True,
    }


@pytest.mark.django_db
def test_ac1_a_confirmed_booking_in_the_period_excludes_the_venue(
    signed_in_coordinator, organiser, catalogue
):
    book(
        make_event(organiser, status=EventStatus.CONFIRMED),
        catalogue["hall"],
        future_at(6, 11),
        future_at(6, 13),
    )

    response = signed_in_coordinator.get(
        SEARCH, {"start": iso(future_at(6, 10)), "end": iso(future_at(6, 12))}
    )

    assert "Grand Hall" not in names(response)


@pytest.mark.django_db
def test_ac1_times_outside_operating_hours_exclude_the_venue(signed_in_coordinator, catalogue):
    response = signed_in_coordinator.get(
        SEARCH, {"start": iso(future_at(6, 16)), "end": iso(future_at(6, 18))}
    )

    assert "Studio" not in names(response)


@pytest.mark.django_db
@pytest.mark.parametrize("attendance,included", [(120, True), (121, False)])
def test_ac2_capacity_boundary_exact_capacity_remains_eligible(
    signed_in_coordinator, catalogue, attendance, included
):
    response = signed_in_coordinator.get(SEARCH, {"attendance": attendance})

    assert ("Studio" in names(response)) is included
    assert "Meeting Room" not in names(response)


@pytest.mark.django_db
def test_ac3_a_venue_without_the_layout_is_excluded(signed_in_coordinator, catalogue):
    response = signed_in_coordinator.get(SEARCH, {"layout": "CLASSROOM"})

    assert names(response) == ["Studio"]


@pytest.mark.django_db
def test_ac4_empty_filters_are_not_applied(signed_in_coordinator, catalogue):
    response = signed_in_coordinator.get(
        SEARCH, {"attendance": "", "layout": "", "facilities": "", "location": ""}
    )

    assert names(response) == ["Grand Hall", "Meeting Room", "Studio"]


@pytest.mark.django_db
def test_ac4_location_and_step_free_access_filters_apply_when_given(
    signed_in_coordinator, catalogue
):
    by_location = signed_in_coordinator.get(SEARCH, {"location": "marina"})
    by_access = signed_in_coordinator.get(SEARCH, {"wheelchair_access": "true"})

    assert names(by_location) == ["Grand Hall", "Studio"]
    assert names(by_access) == ["Grand Hall", "Studio"]


@pytest.mark.django_db
def test_ac5_no_match_gives_a_message_not_an_error(signed_in_coordinator, catalogue):
    response = signed_in_coordinator.get(SEARCH, {"attendance": 5000})

    assert response.status_code == 200
    assert response.data["results"] == []
    assert response.data["message"] == "No venue matched every requirement you entered."


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["attendee", "organiser"])
def test_ac6_attendees_and_clients_cannot_search_venues(api, request, catalogue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    response = api.get(SEARCH, {"attendance": 10})

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params,field",
    [
        ({"attendance": "many"}, "attendance"),
        ({"attendance": "0"}, "attendance"),
        ({"layout": "IGLOO"}, "layout"),
        ({"start": "2026-01-01T10:00:00+08:00"}, "detail"),
    ],
)
def test_invalid_search_input_is_explained(signed_in_coordinator, catalogue, params, field):
    response = signed_in_coordinator.get(SEARCH, params)

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_scrum5_ac3_a_recorded_layout_makes_the_venue_eligible_in_a_layout_search(
    signed_in_venue_staff, api, coordinator, venue
):
    signed_in_venue_staff.patch(
        f"/api/venues/{venue.pk}/", {"layouts": ["THEATRE", "CLASSROOM", "BANQUET"]}, format="json"
    )
    api.force_authenticate(coordinator)

    response = api.get(SEARCH, {"layout": "BANQUET"})

    assert [row["id"] for row in response.data["results"]] == [venue.pk]
