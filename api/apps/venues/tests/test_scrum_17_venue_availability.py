"""SCRUM-17 (US-09.1) - view a venue's availability."""

from datetime import time

import pytest

from apps.core.statuses import EventStatus
from apps.venues.availability import InvalidPeriod, overall, parse_period
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import block, book, iso
from conftest import future_at, make_event, make_venue


def diary(api, venue, start, end):
    return api.get(f"/api/venues/{venue.pk}/availability/", {"start": iso(start), "end": iso(end)})


@pytest.fixture
def office_hours_venue(db):
    return make_venue(name="Office Hours Room", opens_at=time(9, 0), closes_at=time(18, 0))


@pytest.mark.django_db
def test_ac1_a_venues_availability_is_shown_for_the_chosen_period(
    signed_in_coordinator, office_hours_venue
):
    response = diary(signed_in_coordinator, office_hours_venue, future_at(3, 10), future_at(3, 12))

    assert response.status_code == 200
    assert response.data["venue_name"] == "Office Hours Room"
    [segment] = response.data["segments"]
    assert segment["status"] == "AVAILABLE"
    assert (segment["start"], segment["end"]) == (future_at(3, 10), future_at(3, 12))


@pytest.mark.django_db
def test_ac2_each_period_shows_available_tentative_confirmed_or_blocked(
    signed_in_coordinator, organiser, office_hours_venue
):
    confirmed_event = make_event(organiser, status=EventStatus.PLANNING, name="Board Meeting")
    tentative_event = make_event(organiser, status=EventStatus.PLANNING, name="Workshop")
    book(confirmed_event, office_hours_venue, future_at(3, 10), future_at(3, 11))
    book(
        tentative_event,
        office_hours_venue,
        future_at(3, 12),
        future_at(3, 13),
        status=BookingStatus.PENDING,
    )
    block(office_hours_venue, future_at(3, 14), future_at(3, 15), reason="Deep clean")

    response = diary(signed_in_coordinator, office_hours_venue, future_at(3, 9), future_at(3, 16))

    rows = [(s["status"], s["start"], s["end"]) for s in response.data["segments"]]
    assert rows == [
        ("AVAILABLE", future_at(3, 9), future_at(3, 10)),
        ("CONFIRMED", future_at(3, 10), future_at(3, 11)),
        ("AVAILABLE", future_at(3, 11), future_at(3, 12)),
        ("TENTATIVE", future_at(3, 12), future_at(3, 13)),
        ("AVAILABLE", future_at(3, 13), future_at(3, 14)),
        ("BLOCKED", future_at(3, 14), future_at(3, 15)),
        ("AVAILABLE", future_at(3, 15), future_at(3, 16)),
    ]
    segments = response.data["segments"]
    assert segments[1]["event_name"] == "Board Meeting"
    assert segments[3]["event_name"] == "Workshop"
    assert segments[5]["detail"] == "Deep clean"


@pytest.mark.django_db
def test_ac2_rejected_and_withdrawn_requests_do_not_hold_the_venue(
    signed_in_coordinator, organiser, office_hours_venue
):
    event = make_event(organiser, status=EventStatus.PLANNING)
    for status in (BookingStatus.REJECTED, BookingStatus.WITHDRAWN, BookingStatus.RELEASED):
        book(event, office_hours_venue, future_at(3, 10), future_at(3, 11), status=status)

    response = diary(signed_in_coordinator, office_hours_venue, future_at(3, 10), future_at(3, 11))

    assert [s["status"] for s in response.data["segments"]] == ["AVAILABLE"]


@pytest.mark.django_db
def test_ac3_a_change_in_bookings_is_shown_the_next_time(
    signed_in_coordinator, organiser, office_hours_venue
):
    event = make_event(organiser, status=EventStatus.PLANNING)
    period = (future_at(3, 10), future_at(3, 11))
    before = diary(signed_in_coordinator, office_hours_venue, *period)
    booking = book(event, office_hours_venue, *period)
    during = diary(signed_in_coordinator, office_hours_venue, *period)
    booking.status = BookingStatus.WITHDRAWN
    booking.save()
    after = diary(signed_in_coordinator, office_hours_venue, *period)

    assert [s["status"] for s in before.data["segments"]] == ["AVAILABLE"]
    assert [s["status"] for s in during.data["segments"]] == ["CONFIRMED"]
    assert [s["status"] for s in after.data["segments"]] == ["AVAILABLE"]


@pytest.mark.django_db
def test_ac4_time_outside_operating_hours_is_unavailable(signed_in_coordinator, office_hours_venue):
    response = diary(signed_in_coordinator, office_hours_venue, future_at(3, 7), future_at(3, 20))

    rows = [(s["status"], s["start"], s["end"], s["detail"]) for s in response.data["segments"]]
    assert rows == [
        ("UNAVAILABLE", future_at(3, 7), future_at(3, 9), "Outside operating hours"),
        ("AVAILABLE", future_at(3, 9), future_at(3, 18), ""),
        ("UNAVAILABLE", future_at(3, 18), future_at(3, 20), "Outside operating hours"),
    ]


@pytest.mark.django_db
def test_ac4_a_day_the_venue_does_not_open_is_unavailable(signed_in_coordinator):
    day = future_at(3, 10)
    closed_that_day = make_venue(
        name="Weekday Room", operating_days=[d for d in range(7) if d != day.weekday()]
    )

    response = diary(signed_in_coordinator, closed_that_day, future_at(3, 10), future_at(3, 12))

    assert [s["status"] for s in response.data["segments"]] == ["UNAVAILABLE"]


@pytest.mark.django_db
def test_ac4_a_venue_out_of_service_or_without_hours_is_unavailable(signed_in_coordinator):
    closed = make_venue(name="Closed", is_active=False)
    no_hours = make_venue(name="No Hours", opens_at=None, closes_at=None)

    for venue, reason in (
        (closed, "Venue is out of service"),
        (no_hours, "Operating hours have not been recorded"),
    ):
        response = diary(signed_in_coordinator, venue, future_at(3, 10), future_at(3, 12))
        [segment] = response.data["segments"]
        assert (segment["status"], segment["detail"]) == ("UNAVAILABLE", reason)


@pytest.mark.django_db
def test_ac1_a_range_over_several_days_is_cut_at_each_opening_and_closing(
    signed_in_coordinator, office_hours_venue
):
    response = diary(signed_in_coordinator, office_hours_venue, future_at(3, 0), future_at(5, 0))

    available = [s for s in response.data["segments"] if s["status"] == "AVAILABLE"]
    assert [(s["start"], s["end"]) for s in available] == [
        (future_at(3, 9), future_at(3, 18)),
        (future_at(4, 9), future_at(4, 18)),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["attendee", "organiser"])
def test_ac5_attendees_and_clients_cannot_open_the_availability_calendar(
    api, request, venue, fixture_name
):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    response = diary(api, venue, future_at(3, 10), future_at(3, 12))

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start": "2026-01-01T10:00:00+08:00"},
        {"start": "tomorrow", "end": "later"},
        {"start": "2026-01-01T10:00:00", "end": "2026-01-01T12:00:00"},
        {"start": "2026-01-01T12:00:00+08:00", "end": "2026-01-01T10:00:00+08:00"},
        {"start": "2026-01-01T00:00:00+08:00", "end": "2026-03-01T00:00:00+08:00"},
    ],
)
def test_an_invalid_period_is_explained(signed_in_coordinator, venue, params):
    response = signed_in_coordinator.get(f"/api/venues/{venue.pk}/availability/", params)

    assert response.status_code == 400
    assert response.data["detail"]


def test_overall_summary_words():
    assert overall([{"status": "AVAILABLE"}]) == "AVAILABLE"
    assert overall([{"status": "BLOCKED"}]) == "BLOCKED"
    assert overall([{"status": "AVAILABLE"}, {"status": "CONFIRMED"}]) == "PARTIAL"
    assert overall([{"status": "CONFIRMED"}, {"status": "UNAVAILABLE"}]) == "UNAVAILABLE"


def test_parse_period_rejects_missing_values():
    with pytest.raises(InvalidPeriod):
        parse_period(None, None)
