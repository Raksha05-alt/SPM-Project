"""SCRUM-62: comparison, union, permission and real workflow refresh cases."""

from datetime import timedelta

import pytest

from apps.venues.models import VenueBlock
from apps.venues.tests.conftest import make_venue
from apps.venues.tests.test_scrum_11_request_booking import END, START, request_as
from apps.venues.tests.test_scrum_11_request_booking import hall as hall
from apps.venues.tests.test_scrum_67_withdraw_booking import url

pytestmark = pytest.mark.django_db
URL = "/api/venues/compare-availability/"


def compare(api, start=START, end=END):
    return api.get(URL, {"starts_at": start.isoformat(), "ends_at": end.isoformat()})


def test_ac1_ac2_ac3_union_segments_and_all_statuses(signed_in_coordinator, open_venue):
    start, end = START - timedelta(hours=1), END + timedelta(hours=1)
    for left, right in [
        (START, START + timedelta(minutes=45)),
        (START + timedelta(minutes=30), START + timedelta(hours=1)),
    ]:
        VenueBlock.objects.create(venue=open_venue, starts_at=left, ends_at=right, reason="Private")
    full = make_venue(
        name="Fully blocked",
        opens_at=open_venue.opens_at,
        closes_at=open_venue.closes_at,
        operating_days=open_venue.operating_days,
    )
    VenueBlock.objects.create(venue=full, starts_at=start, ends_at=end, reason="Private")
    data = compare(signed_in_coordinator, start, end).data
    rows = {row["venue_id"]: row for row in data["venues"]}
    assert rows[open_venue.pk]["status"] == "partial"
    assert rows[open_venue.pk]["free_segments"] == [
        {"starts_at": start, "ends_at": START},
        {"starts_at": START + timedelta(hours=1), "ends_at": end},
    ]
    assert rows[full.pk]["status"] == "unavailable"
    assert rows[full.pk]["free_segments"] == []
    assert data["message"] == "No venues are available for the whole period."
    make_venue(
        name="Free",
        opens_at=full.opens_at,
        closes_at=full.closes_at,
        operating_days=full.operating_days,
    )
    assert compare(signed_in_coordinator, start, end).data["message"] == ""
    assert "Private" not in str(data)


def test_ac1_ac4_ac5_real_approval_and_withdrawal(api, organiser, coordinator, venue_staff, hall):
    from apps.core.statuses import EventStatus
    from conftest import make_event

    event = make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)
    assert request_as(api, coordinator, event, hall).status_code == 201
    booking = event.venue_bookings.get()
    assert compare(api).data["venues"][0]["available"]
    api.force_authenticate(venue_staff)
    assert (
        api.post(f"/api/venue-bookings/{booking.pk}/approve/", {}, format="json").status_code == 200
    )
    api.force_authenticate(coordinator)
    row = compare(api).data["venues"][0]
    assert row["status"] == "unavailable"
    assert row["reasons"] == ["Approved bookings overlap this period."]
    assert "event_id" not in str(row) and "booking_id" not in str(row)
    assert compare(api, END, END + timedelta(hours=1)).data["venues"][0]["available"]
    assert (
        api.post(
            url(booking), {"expected_status": "APPROVED", "confirm_release": True}, format="json"
        ).status_code
        == 200
    )
    assert compare(api).data["venues"][0]["available"]


@pytest.mark.parametrize("role", ["organiser", "attendee", "tech_staff"])
def test_ac4_forbidden(api, request, role):
    api.force_authenticate(request.getfixturevalue(role))
    assert compare(api).status_code == 403


def test_invalid_empty_and_operating_hours(signed_in_coordinator, open_venue):
    assert signed_in_coordinator.get(URL).status_code == 400
    assert compare(signed_in_coordinator, END, START).status_code == 400
    row = compare(signed_in_coordinator, START.replace(hour=7), START.replace(hour=9)).data[
        "venues"
    ][0]
    assert row["status"] == "partial"
    assert row["free_segments"] == [
        {"starts_at": START.replace(hour=8), "ends_at": START.replace(hour=9)}
    ]
    open_venue.in_service = False
    open_venue.save()
    assert compare(signed_in_coordinator).data["venues"][0]["status"] == "unavailable"
    open_venue.delete()
    assert compare(signed_in_coordinator).data["message"]
