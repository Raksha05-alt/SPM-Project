"""SCRUM-88 tentative holds, occupancy, deadlines and coordinator actions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.period_conflicts import venue_conflicts
from apps.notifications.models import Notification, NotificationKind
from apps.safety.services import confirmation_gaps
from apps.venues.availability import availability
from apps.venues.bookings import (
    BookingValidationError,
    VenueNotAvailable,
    approve_booking,
    create_booking_record,
    request_booking,
)
from apps.venues.holds import process_holds
from apps.venues.models import BookingStatus, Venue, VenueBooking, VenueBookingHistory
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


def test_staff_hold_and_assigned_coordinator_confirm(
    api, request_record, venue_staff, coordinator, second_coordinator
):
    booking = request_record
    path = f"/api/venue-bookings/{booking.pk}"
    deadline = timezone.now() + timedelta(hours=6)
    api.force_authenticate(venue_staff)
    response = api.post(f"{path}/approve/", {"hold_until": deadline.isoformat()})
    assert response.status_code == 200, response.data
    assert response.data["booking"]["status"] == BookingStatus.HELD
    assert Notification.objects.filter(
        event=booking.event, kind=NotificationKind.VENUE_DECIDED, recipient=coordinator
    ).exists()
    assert any("hold" in gap.lower() for gap in confirmation_gaps(booking.event))

    assert api.post(f"{path}/confirm-hold/").status_code == 403
    api.force_authenticate(second_coordinator)
    assert api.post(f"{path}/confirm-hold/").status_code == 403
    api.force_authenticate(coordinator)
    response = api.post(f"{path}/confirm-hold/")
    assert response.status_code == 200, response.data
    assert response.data["booking"]["status"] == BookingStatus.APPROVED
    booking.refresh_from_db()
    assert booking.decided_by == venue_staff
    assert booking.hold_until == deadline
    assert list(
        VenueBookingHistory.objects.filter(booking=booking)
        .order_by("pk")
        .values_list("to_status", "actor_id")
    )[-2:] == [(BookingStatus.HELD, venue_staff.pk), (BookingStatus.APPROVED, coordinator.pk)]


@pytest.mark.parametrize("expiry", ["past", "booking_start"])
def test_staff_cannot_approve_hold_with_invalid_deadline(
    signed_in_venue_staff, request_record, expiry
):
    deadline = (
        timezone.now() - timedelta(seconds=1) if expiry == "past" else request_record.starts_at
    )
    response = signed_in_venue_staff.post(
        f"/api/venue-bookings/{request_record.pk}/approve/", {"hold_until": deadline.isoformat()}
    )
    assert response.status_code == 400
    assert "hold_until" in response.data
    request_record.refresh_from_db()
    assert request_record.status == BookingStatus.PENDING


def test_deadline_revision_notifies_and_resets_the_reminder(
    signed_in_venue_staff, request_record, venue_staff, coordinator, monkeypatch
):
    booking = request_record
    now = timezone.now()
    first = now + timedelta(hours=25)
    approve_booking(booking, venue_staff, hold_until=first)
    assert process_holds() == (0, 0)

    monkeypatch.setattr(timezone, "now", lambda: first - timedelta(hours=24))
    assert process_holds() == (0, 1)
    assert process_holds() == (0, 0)
    revised = now + timedelta(hours=12)
    path = f"/api/venue-bookings/{booking.pk}/hold-expiry/"
    for _ in range(2):
        response = signed_in_venue_staff.post(path, {"hold_until": revised.isoformat()})
        assert response.status_code == 200, response.data

    booking.refresh_from_db()
    assert booking.hold_until == revised
    assert (
        VenueBookingHistory.objects.filter(
            booking=booking,
            from_status=BookingStatus.HELD,
            to_status=BookingStatus.HELD,
            actor=venue_staff,
        ).count()
        == 1
    )
    notices = Notification.objects.filter(event=booking.event, recipient=coordinator)
    assert notices.filter(kind=NotificationKind.VENUE_HOLD_UPDATED).count() == 1
    assert process_holds() == (0, 1)
    assert process_holds() == (0, 0)
    assert notices.filter(kind=NotificationKind.VENUE_HOLD_REMINDER).count() == 2


def test_deadline_refuses_confirmation_and_worker_records_expiry_once(
    api, request_record, venue_staff, coordinator, monkeypatch
):
    booking = request_record
    deadline = timezone.now() + timedelta(hours=2)
    approve_booking(booking, venue_staff, hold_until=deadline)
    monkeypatch.setattr(timezone, "now", lambda: deadline)

    api.force_authenticate(coordinator)
    response = api.get(f"/api/events/{booking.event_id}/venue-bookings/")
    assert response.status_code == 200, response.data
    assert response.data[0]["status"] == BookingStatus.EXPIRED
    response = api.post(f"/api/venue-bookings/{booking.pk}/confirm-hold/")
    assert response.status_code == 409
    response = api.post(f"/api/events/{booking.event_id}/confirm/")
    assert response.status_code == 409
    assert any("expir" in gap.lower() for gap in response.data["missing"])

    call_command("process_venue_holds")
    call_command("process_venue_holds")
    booking.refresh_from_db()
    assert booking.status == BookingStatus.EXPIRED
    assert (
        VenueBookingHistory.objects.filter(booking=booking, to_status=BookingStatus.EXPIRED).count()
        == 1
    )
    assert (
        Notification.objects.filter(
            event=booking.event, recipient=coordinator, kind=NotificationKind.VENUE_HOLD_EXPIRED
        ).count()
        == 1
    )
    assert availability(booking.venue, booking.starts_at, booking.ends_at)["available"]
    assert api.post(f"/api/venue-bookings/{booking.pk}/confirm-hold/").status_code == 409


def test_confirmed_change_conflict_counts_only_live_holds(
    request_record, organiser, coordinator, venue_staff
):
    held = approve_booking(
        request_record, venue_staff, hold_until=timezone.now() + timedelta(hours=2)
    )
    original_start = held.starts_at - timedelta(days=1)
    original_end = held.ends_at - timedelta(days=1)
    event = make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        coordinator=coordinator,
        preferred_start=original_start,
        preferred_end=original_end,
    )
    original = create_booking_record(
        event=event,
        venue=held.venue,
        starts_at=original_start,
        ends_at=original_end,
        requested_by=coordinator,
        attendance=30,
    )
    VenueBooking.objects.filter(pk=original.pk).update(status=BookingStatus.APPROVED)
    proposed = {"preferred_start": held.starts_at, "preferred_end": held.ends_at}
    assert [entry["id"] for entry in venue_conflicts(event, proposed)[0]["conflicts"]] == [held.pk]

    VenueBooking.objects.filter(pk=held.pk).update(hold_until=timezone.now() - timedelta(seconds=1))
    assert venue_conflicts(event, proposed)[0]["conflicts"] == []
    original.refresh_from_db()
    assert original.starts_at == original_start
    assert original.status == BookingStatus.APPROVED


def test_second_request_cannot_replace_a_live_hold_but_can_after_expiry(
    request_record, venue_staff, coordinator, open_venue
):
    first = approve_booking(
        request_record, venue_staff, hold_until=timezone.now() + timedelta(hours=2)
    )
    second = create_booking_record(
        event=first.event,
        venue=open_venue,
        starts_at=first.starts_at + timedelta(hours=3),
        ends_at=first.ends_at + timedelta(hours=3),
        requested_by=coordinator,
        attendance=30,
        session=first.session,
    )
    with pytest.raises(BookingValidationError):
        approve_booking(second, venue_staff)
    second.refresh_from_db()
    assert second.status == BookingStatus.PENDING

    VenueBooking.objects.filter(pk=first.pk).update(
        hold_until=timezone.now() - timedelta(seconds=1)
    )
    assert approve_booking(second, venue_staff).status == BookingStatus.APPROVED
    first.refresh_from_db()
    assert first.status == BookingStatus.EXPIRED


def test_cancel_releases_the_hold_using_the_current_cancellation_version(
    api, request_record, venue_staff, coordinator, monkeypatch
):
    booking = approve_booking(
        request_record, venue_staff, hold_until=timezone.now() + timedelta(hours=2)
    )
    api.force_authenticate(coordinator)
    path = f"/api/events/{booking.event_id}"
    preview = api.get(f"{path}/cancellation-preview/").data
    assert preview["venue_bookings"][0]["status"] == BookingStatus.HELD
    revised = booking.hold_until + timedelta(hours=1)

    api.force_authenticate(venue_staff)
    updated = api.post(
        f"/api/venue-bookings/{booking.pk}/hold-expiry/", {"hold_until": revised.isoformat()}
    )
    assert updated.status_code == 200, updated.data

    api.force_authenticate(coordinator)
    payload = {
        "confirm_cancel": True,
        "reason": "Event cancelled by the client",
        "expected_version": preview["version"],
    }
    assert api.post(f"{path}/cancel/", payload, format="json").status_code == 409
    payload["expected_version"] = api.get(f"{path}/cancellation-preview/").data["version"]
    cancelled = api.post(f"{path}/cancel/", payload, format="json")
    assert cancelled.status_code == 200, cancelled.data
    booking.refresh_from_db()
    assert booking.status == BookingStatus.WITHDRAWN
    assert availability(booking.venue, booking.starts_at, booking.ends_at)["available"]
    monkeypatch.setattr(timezone, "now", lambda: revised)
    assert process_holds() == (0, 0)


@pytest.mark.django_db(transaction=True)
def test_two_workers_cannot_expire_or_notify_for_the_same_hold_twice(
    request_record, venue_staff, coordinator, monkeypatch
):
    booking = request_record
    deadline = timezone.now() + timedelta(hours=1)
    approve_booking(booking, venue_staff, hold_until=deadline)
    monkeypatch.setattr(timezone, "now", lambda: deadline)
    simultaneous = Barrier(2)

    def worker():
        try:
            simultaneous.wait(timeout=5)
            return process_holds()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = [workers.submit(worker) for _ in range(2)]
        assert sorted(result.result(timeout=10) for result in pending) == [(0, 0), (1, 0)]

    booking.refresh_from_db()
    assert booking.status == BookingStatus.EXPIRED
    assert (
        VenueBookingHistory.objects.filter(booking=booking, to_status=BookingStatus.EXPIRED).count()
        == 1
    )
    assert (
        Notification.objects.filter(
            event=booking.event, recipient=coordinator, kind=NotificationKind.VENUE_HOLD_EXPIRED
        ).count()
        == 1
    )


def test_expiry_rolls_back_if_the_notice_cannot_be_saved(request_record, venue_staff, monkeypatch):
    booking = request_record
    deadline = timezone.now() + timedelta(hours=1)
    approve_booking(booking, venue_staff, hold_until=deadline)
    monkeypatch.setattr(timezone, "now", lambda: deadline)

    def unavailable(**kwargs):
        raise RuntimeError("Notification unavailable")

    monkeypatch.setattr("apps.venues.holds.notify", unavailable)
    with pytest.raises(RuntimeError, match="Notification unavailable"):
        process_holds()
    booking.refresh_from_db()
    assert booking.status == BookingStatus.HELD
    assert not VenueBookingHistory.objects.filter(
        booking=booking, to_status=BookingStatus.EXPIRED
    ).exists()
