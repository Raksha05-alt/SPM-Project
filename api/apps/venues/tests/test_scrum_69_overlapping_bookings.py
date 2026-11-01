"""SCRUM-69 G08: persisted occupancy and atomic transition regression cases.

HTTP request/decision/cancellation journeys await gates G09/G10/INT-03.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection

from apps.core.statuses import EventStatus
from apps.venues.availability import availability
from apps.venues.bookings import BookingValidationError, create_booking_record, transition_booking
from apps.venues.models import BookingStatus
from apps.venues.occupancy import clashes
from conftest import make_event

START = datetime(2027, 3, 1, 10, tzinfo=ZoneInfo("Asia/Singapore"))
END = START + timedelta(hours=2)


def pending(organiser, coordinator, venue, **overrides):
    return create_booking_record(
        requested_by=coordinator,
        event=make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator),
        venue=venue,
        starts_at=overrides.get("start", START),
        ends_at=overrides.get("end", END),
        attendance=60,
    )


@pytest.mark.django_db
def test_01_overlap_identifies_event_and_03_refuses_approval(
    open_venue, organiser, coordinator, venue_staff
):
    first = pending(organiser, coordinator, open_venue)
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    second = pending(
        organiser,
        coordinator,
        open_venue,
        start=END - timedelta(minutes=1),
        end=END + timedelta(hours=1),
    )
    result = availability(open_venue, second.starts_at, second.ends_at)
    assert result["status"] == "booked"
    assert result["conflicts"] == [
        {"id": first.pk, "event_id": first.event_id, "starts_at": START, "ends_at": END}
    ]
    with pytest.raises(BookingValidationError, match=str(first.event_id)):
        transition_booking(second, BookingStatus.APPROVED, venue_staff)
    second.refresh_from_db()
    assert second.status == BookingStatus.PENDING
    assert second.decided_at is None
    assert second.history.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "start,end", [(START - timedelta(hours=2), START), (END, END + timedelta(hours=1))]
)
def test_02_adjacent_periods_are_free(open_venue, organiser, coordinator, venue_staff, start, end):
    first = pending(organiser, coordinator, open_venue)
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    assert availability(open_venue, start, end)["available"] is True


@pytest.mark.django_db
def test_04_cancelled_event_no_longer_occupies(open_venue, organiser, coordinator, venue_staff):
    first = pending(organiser, coordinator, open_venue)
    second = pending(organiser, coordinator, open_venue)
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    # Model-level cancellation exclusion only; the real cancellation action is a later gate.
    first.event.status = EventStatus.CANCELLED
    first.event.save(update_fields=["status"])
    assert not clashes(open_venue, START, END).exists()
    transition_booking(second, BookingStatus.APPROVED, venue_staff)
    assert second.status == BookingStatus.APPROVED


@pytest.mark.django_db
def test_05_pending_does_not_reserve_and_fresh_read_changes(
    open_venue, organiser, coordinator, venue_staff
):
    first = pending(organiser, coordinator, open_venue)
    second = pending(organiser, coordinator, open_venue)
    assert not clashes(open_venue, START, END).exists()
    transition_booking(first, BookingStatus.APPROVED, venue_staff)
    assert list(clashes(open_venue, second.starts_at, second.ends_at)) == [first]
    transition_booking(first, BookingStatus.WITHDRAWN, venue_staff)
    assert availability(open_venue, START, END)["available"] is True


@pytest.mark.django_db(transaction=True)
def test_05_concurrent_approvals_cannot_both_succeed(
    open_venue, organiser, coordinator, venue_staff
):
    if connection.vendor != "postgresql":
        pytest.skip("Resource row locks require PostgreSQL")
    bookings = [pending(organiser, coordinator, open_venue) for _ in range(2)]
    barrier = Barrier(2)

    def approve(booking):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                transition_booking(booking, BookingStatus.APPROVED, venue_staff)
                return "approved"
            except BookingValidationError:
                return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, bookings)) == ["approved", "conflict"]
    for booking in bookings:
        booking.refresh_from_db()
    assert sorted(b.status for b in bookings) == [BookingStatus.APPROVED, BookingStatus.PENDING]


@pytest.mark.django_db
def test_bulk_occupancy_matches_direct_checks_without_per_venue_queries(
    open_venue, organiser, coordinator, venue_staff, django_assert_num_queries
):
    from apps.venues.models import Venue
    from apps.venues.occupancy import occupancy_prefetch

    approved = pending(organiser, coordinator, open_venue)
    transition_booking(approved, BookingStatus.APPROVED, venue_staff)
    pending(organiser, coordinator, open_venue)
    cancelled = pending(organiser, coordinator, open_venue)
    # Establish historical approved occupancy belonging to a cancelled event.
    type(cancelled).objects.filter(pk=cancelled.pk).update(status=BookingStatus.APPROVED)
    cancelled.event.status = EventStatus.CANCELLED
    cancelled.event.save(update_fields=["status"])
    withdrawn = pending(organiser, coordinator, open_venue)
    transition_booking(withdrawn, BookingStatus.WITHDRAWN, venue_staff)
    rejected = pending(organiser, coordinator, open_venue)
    transition_booking(rejected, BookingStatus.REJECTED, venue_staff, reason="Not required")

    periods = [
        (START, END),
        (END - timedelta(minutes=1), END + timedelta(hours=1)),
        (START - timedelta(hours=2), START),
        (END, END + timedelta(hours=1)),
    ]
    expected = [availability(open_venue, start, end) for start, end in periods]
    with django_assert_num_queries(3):
        loaded = Venue.objects.prefetch_related("blocks", occupancy_prefetch()).get(
            pk=open_venue.pk
        )
    assert [b.pk for b in loaded.occupancy_bookings] == [approved.pk]
    with django_assert_num_queries(0):
        assert [availability(loaded, start, end) for start, end in periods] == expected

    # Each new read obtains a new snapshot after a write.
    transition_booking(approved, BookingStatus.WITHDRAWN, venue_staff)
    loaded = Venue.objects.prefetch_related("blocks", occupancy_prefetch()).get(pk=open_venue.pk)
    with django_assert_num_queries(0):
        assert availability(loaded, START, END)["available"] is True
