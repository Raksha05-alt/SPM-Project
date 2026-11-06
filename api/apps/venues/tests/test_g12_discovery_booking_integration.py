"""INT-01: actual request/approval/withdrawal actions and fresh discovery reads.

Cancellation compatibility uses the existing shared event-state service. The
coordinator cancellation/resource-release API is a later G16b handoff.
"""

import datetime
import json

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.services import transition_event
from apps.venues.models import VenueShortlistEntry
from apps.venues.tests.test_scrum_11_request_booking import END, START, request_as
from apps.venues.tests.test_scrum_11_request_booking import hall as hall
from conftest import make_event

pytestmark = pytest.mark.django_db
SEARCH = "/api/venues/search/"
CRITERIA = {
    "start": START.isoformat(),
    "end": END.isoformat(),
    "attendance": 60,
    "layout": "THEATRE",
    "facilities": ["Video conferencing"],
}


@pytest.fixture
def candidate(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.APPROVED,
        coordinator=coordinator,
        preferred_start=START,
        preferred_end=END,
        expected_attendance=60,
    )


def shortlist(event):
    return f"/api/events/{event.pk}/venue-shortlist/"


def save(api, coordinator, event, hall, criteria=None):
    api.force_authenticate(coordinator)
    response = api.post(
        shortlist(event),
        {"venue_id": hall.pk, "criteria": CRITERIA if criteria is None else criteria},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def request(api, organiser, coordinator, hall, **overrides):
    event = make_event(
        organiser,
        status=EventStatus.APPROVED,
        coordinator=coordinator,
        preferred_start=START,
        preferred_end=END,
        expected_attendance=60,
        **overrides,
    )
    response = request_as(api, coordinator, event, hall)
    assert response.status_code == 201, response.data
    return event.venue_bookings.get()


def approve(api, staff, booking):
    api.force_authenticate(staff)
    response = api.post(f"/api/venue-bookings/{booking.pk}/approve/", {}, format="json")
    assert response.status_code == 200, response.data


def withdraw(api, coordinator, booking):
    api.force_authenticate(coordinator)
    response = api.post(
        f"/api/events/{booking.event_id}/venue-bookings/{booking.pk}/withdraw/",
        {"expected_status": "APPROVED", "confirm_release": True},
        format="json",
    )
    assert response.status_code == 200, response.data


def reads(api, coordinator, candidate, hall, criteria=None):
    api.force_authenticate(coordinator)
    period = CRITERIA if criteria is None else criteria
    search = api.get(SEARCH, period)
    calendar = api.get(
        f"/api/venues/{hall.pk}/availability/",
        {
            "starts_at": period["start"],
            "ends_at": period["end"],
        },
    )
    saved = api.get(shortlist(candidate))
    assert (search.status_code, calendar.status_code, saved.status_code) == (200, 200, 200)
    return search.data, calendar.data, saved.data


def test_g12_01_real_approval_and_withdrawal_refresh_search_calendar_and_saved_entry(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
):
    original = save(api, coordinator, candidate, hall)
    booking = request(api, organiser, coordinator, hall)
    available, calendar, saved = reads(api, coordinator, candidate, hall)
    assert [row["venue"]["id"] for row in available["results"]] == [hall.pk]
    assert available["availability_integrated"] is True
    assert available["booking_occupancy_integrated"] is True
    assert available["holds_integrated"] is False
    assert calendar["available"] is True  # Pending requests do not reserve the venue.
    assert saved["entries"][0]["match"]["availability_status"] == "AVAILABLE"

    approve(api, venue_staff, booking)
    occupied, calendar, saved = reads(api, coordinator, candidate, hall)
    assert occupied["results"] == []
    assert calendar["status"] == "booked"
    entry = saved["entries"][0]
    assert entry["id"] == original["id"]
    assert entry["search_criteria"] == original["search_criteria"]
    assert entry["match"]["availability_status"] == "UNAVAILABLE"
    check = next(c for c in entry["match"]["criteria"] if c["key"] == "approved_bookings")
    assert check["result"] == "UNMET"
    assert str(booking.event_id) in check["message"]

    withdraw(api, coordinator, booking)
    available, calendar, saved = reads(api, coordinator, candidate, hall)
    assert [row["venue"]["id"] for row in available["results"]] == [hall.pk]
    assert calendar["available"] is True
    assert saved["entries"][0]["id"] == original["id"]
    assert saved["entries"][0]["match"]["availability_status"] == "AVAILABLE"
    assert VenueShortlistEntry.objects.get().search_criteria == original["search_criteria"]


def test_g12_02_rejected_request_does_not_obstruct_the_period(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
):
    save(api, coordinator, candidate, hall)
    booking = request(api, organiser, coordinator, hall)
    api.force_authenticate(venue_staff)
    assert (
        api.post(
            f"/api/venue-bookings/{booking.pk}/reject/",
            {"reason": "Alternative arrangement agreed"},
            format="json",
        ).status_code
        == 200
    )
    search, calendar, saved = reads(api, coordinator, candidate, hall)
    assert len(search["results"]) == 1
    assert calendar["available"] is True
    assert saved["entries"][0]["match"]["availability_status"] == "AVAILABLE"


@pytest.mark.parametrize(
    "offset_start,offset_end,expected",
    [
        (-7200, 0, True),
        (7200, 10800, True),
        (-1, 1, False),
        (7199, 7201, False),
    ],
)
def test_g12_03_half_open_booking_boundaries_agree_across_reads(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
    offset_start,
    offset_end,
    expected,
):
    booking = request(api, organiser, coordinator, hall)
    criteria = {
        **CRITERIA,
        "start": (START + datetime.timedelta(seconds=offset_start)).isoformat(),
        "end": (START + datetime.timedelta(seconds=offset_end)).isoformat(),
    }
    original = save(api, coordinator, candidate, hall, criteria=criteria)
    approve(api, venue_staff, booking)
    search, calendar, saved = reads(api, coordinator, candidate, hall, criteria)
    assert bool(search["results"]) is expected
    assert calendar["available"] is expected
    entry = saved["entries"][0]
    assert entry["id"] == original["id"]
    assert entry["search_criteria"] == original["search_criteria"]
    assert entry["match"]["availability_status"] == ("AVAILABLE" if expected else "UNAVAILABLE")


def test_g12_04_stale_search_and_forged_exclusion_cannot_add_an_occupied_venue(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
):
    api.force_authenticate(coordinator)
    assert api.get(SEARCH, CRITERIA).data["results"]
    booking = request(api, organiser, coordinator, hall)
    approve(api, venue_staff, booking)
    api.force_authenticate(coordinator)
    assert api.get(SEARCH, {**CRITERIA, "exclude_booking_id": booking.pk}).data["results"] == []
    response = api.post(
        shortlist(candidate),
        {
            "venue_id": hall.pk,
            "criteria": {**CRITERIA, "exclude_booking_id": booking.pk},
        },
        format="json",
    )
    assert response.status_code == 400
    assert not VenueShortlistEntry.objects.exists()
    assert not AuditLog.objects.filter(action=f"POST {shortlist(candidate)}", allowed=True).exists()


def test_g12_05_cancelled_record_no_longer_occupies_without_erasing_booking_history(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
):
    save(api, coordinator, candidate, hall)
    booking = request(api, organiser, coordinator, hall)
    approve(api, venue_staff, booking)
    booking.event.refresh_from_db()
    transition_event(booking.event, EventStatus.CANCELLED, coordinator)
    search, calendar, saved = reads(api, coordinator, candidate, hall)
    assert len(search["results"]) == 1
    assert calendar["available"] is True
    assert saved["entries"][0]["match"]["availability_status"] == "AVAILABLE"
    assert booking.history.filter(to_status="APPROVED").exists()


def test_g12_06_disruption_keeps_an_independent_date_block(
    api,
    organiser,
    coordinator,
    venue_staff,
    candidate,
    hall,
):
    save(api, coordinator, candidate, hall)
    booking = request(api, organiser, coordinator, hall)
    approve(api, venue_staff, booking)
    api.force_authenticate(venue_staff)
    block = api.post(
        f"/api/venues/{hall.pk}/blocks/",
        {
            "starts_at": START.isoformat(),
            "ends_at": END.isoformat(),
            "reason": "Access inspection",
        },
        format="json",
    )
    assert block.status_code == 201
    # SCRUM-86: a staff block now releases occupancy through Disrupted,
    # retaining the original approval rather than requiring withdrawal.
    booking.refresh_from_db()
    assert booking.status == "DISRUPTED"
    assert booking.history.filter(to_status="APPROVED").exists()
    search, calendar, saved = reads(api, coordinator, candidate, hall)
    assert search["results"] == []
    assert calendar["status"] == "blocked"
    assert saved["entries"][0]["match"]["availability_status"] == "UNAVAILABLE"
    api.force_authenticate(venue_staff)
    assert api.delete(f"/api/venues/{hall.pk}/blocks/{block.data['id']}/").status_code == 204
    booking.refresh_from_db()
    assert booking.status == "DISRUPTED"
    assert (
        reads(api, coordinator, candidate, hall)[2]["entries"][0]["match"]["availability_status"]
        == "AVAILABLE"
    )


def test_g12_07_cross_client_booking_details_remain_private(
    api,
    other_organiser,
    coordinator,
    second_coordinator,
    venue_staff,
    candidate,
    hall,
):
    save(api, coordinator, candidate, hall)
    booking = request(
        api,
        other_organiser,
        second_coordinator,
        hall,
        name="Private client planning",
        description="Do not disclose this event description",
    )
    approve(api, venue_staff, booking)
    _, calendar, saved = reads(api, coordinator, candidate, hall)
    text = json.dumps(saved)
    assert "Private client planning" not in text
    assert "Do not disclose" not in text
    assert set(calendar["conflicts"][0]) == {"id", "event_id", "starts_at", "ends_at"}
    assert api.get(f"/api/events/{booking.event_id}/").status_code == 403


def test_g12_08_missing_dates_remain_unverified_while_booking_capability_is_present(
    api,
    coordinator,
    candidate,
    hall,
):
    candidate.preferred_start = candidate.preferred_end = None
    candidate.save()
    save(api, coordinator, candidate, hall, criteria={})
    api.force_authenticate(coordinator)
    result = api.get(SEARCH).data
    assert result["availability_integrated"] is True
    assert result["holds_integrated"] is False
    assert result["results"][0]["availability_status"] == "UNVERIFIED"
    assert (
        api.get(shortlist(candidate)).data["entries"][0]["match"]["availability_status"]
        == "UNVERIFIED"
    )
