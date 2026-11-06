"""SCRUM-85: real persisted bookings and independent buffer boundary checks."""

from datetime import time, timedelta

import pytest

from apps.safety.services import arrangement_gaps
from apps.venues.availability import availability
from apps.venues.bookings import BookingValidationError, approve_booking, transition_booking
from apps.venues.models import BookingStatus, Venue
from apps.venues.occupancy import booking_review, effective_interval, occupancy_prefetch
from apps.venues.tests.test_scrum_69_overlapping_bookings import END, START, pending

pytestmark = pytest.mark.django_db


def buffers(venue):
    venue.setup_minutes = 30
    venue.turnaround_minutes = 45
    venue.save()
    return venue


def test_effective_interval_and_zero_defaults(open_venue):
    assert effective_interval(open_venue, START, END) == (START, END)
    buffers(open_venue)
    assert effective_interval(open_venue, START, END) == (
        START - timedelta(minutes=30),
        END + timedelta(minutes=45),
    )


@pytest.mark.parametrize("minute,conflict", [(15, False), (14, True)])
def test_buffered_adjacency_direct_prefetched_and_approval(
    open_venue, organiser, coordinator, venue_staff, minute, conflict
):
    buffers(open_venue)
    first = pending(organiser, coordinator, open_venue)
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    start = START.replace(hour=13, minute=minute)
    end = start + timedelta(hours=1)
    loaded = Venue.objects.prefetch_related("blocks", occupancy_prefetch()).get(pk=open_venue.pk)
    for venue in (open_venue, loaded):
        result = availability(venue, start, end)
        assert bool(result["conflicts"]) is conflict
        assert result["available"] is not conflict
    second = pending(organiser, coordinator, open_venue, start=start, end=end)
    if conflict:
        with pytest.raises(BookingValidationError):
            transition_booking(second, BookingStatus.APPROVED, venue_staff)
    else:
        transition_booking(second, BookingStatus.APPROVED, venue_staff)


def test_buffer_edit_preserves_and_flags_bookings(
    signed_in_venue_staff, open_venue, organiser, coordinator, venue_staff
):
    first = pending(organiser, coordinator, open_venue)
    second = pending(
        organiser,
        coordinator,
        open_venue,
        start=END + timedelta(minutes=60),
        end=END + timedelta(hours=2),
    )
    for booking in (first, second):
        transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    response = signed_in_venue_staff.patch(
        f"/api/venues/{open_venue.pk}/",
        {"setup_minutes": 30, "turnaround_minutes": 45},
        format="json",
    )
    assert response.status_code == 200
    for booking in (first, second):
        booking.refresh_from_db()
        assert booking.status == BookingStatus.APPROVED
        assert booking_review(booking)["conflicts"]
        assert any("setup/turnaround" in gap for gap in arrangement_gaps(booking.event))


@pytest.mark.parametrize("field", ["setup_minutes", "turnaround_minutes"])
@pytest.mark.parametrize("value,code", [(-1, 400), (0, 200), (1.5, 400), (None, 400)])
def test_buffer_validation(signed_in_venue_staff, open_venue, field, value, code):
    response = signed_in_venue_staff.patch(
        f"/api/venues/{open_venue.pk}/", {field: value}, format="json"
    )
    assert response.status_code == code


def test_outside_hours_buffer_warns_but_staff_can_approve(
    open_venue, organiser, coordinator, venue_staff
):
    buffers(open_venue)
    open_venue.opens_at = time(10)
    open_venue.save()
    booking = pending(organiser, coordinator, open_venue)
    assert availability(open_venue, START, END)["available"]
    assert "outside operating hours" in booking_review(booking)["warnings"][0]
    approve_booking(booking, venue_staff)
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


@pytest.mark.parametrize("minute,available", [(15, True), (14, False)])
def test_search_shortlist_and_comparison_use_same_boundaries(
    open_venue, organiser, coordinator, venue_staff, minute, available
):
    from apps.venues.availability import comparison_availability
    from apps.venues.discovery import assess_venue, search_venues
    from apps.venues.suitability import Requirements, assess

    buffers(open_venue)
    first = pending(organiser, coordinator, open_venue)
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    start = START.replace(hour=13, minute=minute)
    end = start + timedelta(hours=1)
    criteria = {"start": start.isoformat(), "end": end.isoformat()}
    assert bool(search_venues(criteria)) is available
    assert (assess_venue(open_venue, criteria)["availability_status"] == "AVAILABLE") is available
    assert comparison_availability(open_venue, start, end)["available"] is available
    open_venue.opens_at = time(13)
    result = assess(open_venue, Requirements(starts_at=start, ends_at=end))
    assert result.suitable
    assert result.warnings


def test_buffer_update_rolls_back_if_safety_invalidation_fails(
    signed_in_venue_staff, open_venue, organiser, coordinator, venue_staff
):
    from unittest.mock import patch

    booking = pending(organiser, coordinator, open_venue)
    transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    with patch("apps.venues.views.arrangements_changed", side_effect=RuntimeError("failure")):
        with pytest.raises(RuntimeError):
            signed_in_venue_staff.patch(
                f"/api/venues/{open_venue.pk}/", {"setup_minutes": 30}, format="json"
            )
    open_venue.refresh_from_db()
    assert open_venue.setup_minutes == 0
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


def test_coordinator_cannot_change_buffers(signed_in_coordinator, open_venue):
    response = signed_in_coordinator.patch(
        f"/api/venues/{open_venue.pk}/", {"setup_minutes": 30}, format="json"
    )
    assert response.status_code == 403
    open_venue.refresh_from_db()
    assert open_venue.setup_minutes == 0
