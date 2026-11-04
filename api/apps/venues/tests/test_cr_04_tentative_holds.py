"""SCRUM-88 base: stored hold deadlines and expiry-aware venue occupancy."""

from datetime import datetime, time, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.venues.availability import availability
from apps.venues.bookings import VenueNotAvailable, create_booking_record, request_booking
from apps.venues.models import BookingStatus, Venue, VenueBooking
from apps.venues.occupancy import occupancy_prefetch
from conftest import make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_record(organiser, coordinator, open_venue):
    start = timezone.make_aware(
        datetime.combine(timezone.localdate() + timedelta(days=2), time(10))
    )
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    return create_booking_record(
        event=event,
        venue=open_venue,
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        requested_by=coordinator,
        attendance=30,
    )


def test_buffered_hold_blocks_availability_and_requests_until_its_deadline(
    request_record, organiser, coordinator
):
    existing = request_record
    venue = existing.venue
    venue.setup_minutes = venue.turnaround_minutes = 15
    venue.save(update_fields=["setup_minutes", "turnaround_minutes"])
    candidate = {
        "event": make_event(
            organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=30
        ),
        "venue": venue,
        "requested_by": coordinator,
        "starts_at": existing.ends_at + timedelta(minutes=20),
        "ends_at": existing.ends_at + timedelta(hours=1),
        "attendance": 30,
    }

    def read_availability():
        return availability(venue, candidate["starts_at"], candidate["ends_at"])

    # A pending booking does not reserve the room.
    assert read_availability()["available"]
    # Seed the persisted state directly. The staff approval action follows in the integration slice.
    VenueBooking.objects.filter(pk=existing.pk).update(
        status=BookingStatus.HELD, hold_until=timezone.now() + timedelta(hours=1)
    )
    assert [entry["id"] for entry in read_availability()["conflicts"]] == [existing.pk]
    with pytest.raises(VenueNotAvailable):
        request_booking(**candidate)

    VenueBooking.objects.filter(pk=existing.pk).update(
        hold_until=timezone.now() - timedelta(seconds=1)
    )
    assert read_availability()["available"]
    assert request_booking(**candidate).status == BookingStatus.PENDING
    existing.refresh_from_db()
    assert existing.status == BookingStatus.HELD


def test_prefetched_hold_frees_the_room_at_exact_expiry(request_record, monkeypatch):
    deadline = timezone.now() + timedelta(hours=1)
    VenueBooking.objects.filter(pk=request_record.pk).update(
        status=BookingStatus.HELD, hold_until=deadline
    )
    venue = Venue.objects.prefetch_related("blocks", occupancy_prefetch()).get(
        pk=request_record.venue_id
    )
    assert [booking.pk for booking in venue.occupancy_bookings] == [request_record.pk]

    monkeypatch.setattr(timezone, "now", lambda: deadline - timedelta(microseconds=1))
    assert not availability(venue, request_record.starts_at, request_record.ends_at)["available"]

    monkeypatch.setattr(timezone, "now", lambda: deadline)
    assert availability(venue, request_record.starts_at, request_record.ends_at)["available"]


def test_cancelled_event_cannot_block_a_venue_with_a_live_hold(request_record):
    VenueBooking.objects.filter(pk=request_record.pk).update(
        status=BookingStatus.HELD, hold_until=timezone.now() + timedelta(hours=1)
    )
    request_record.event.status = EventStatus.CANCELLED
    request_record.event.save(update_fields=["status"])

    assert availability(request_record.venue, request_record.starts_at, request_record.ends_at)[
        "available"
    ]


@pytest.mark.parametrize("invalid_deadline", ["missing", "at_start", "after_start"])
def test_database_refuses_a_held_booking_without_a_deadline_before_start(
    request_record, invalid_deadline
):
    deadline = {
        "missing": None,
        "at_start": request_record.starts_at,
        "after_start": request_record.starts_at + timedelta(seconds=1),
    }[invalid_deadline]
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueBooking.objects.filter(pk=request_record.pk).update(
            status=BookingStatus.HELD, hold_until=deadline
        )

    request_record.refresh_from_db()
    assert request_record.status == BookingStatus.PENDING
    assert request_record.hold_until is None
