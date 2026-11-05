"""US-73 / SCRUM-73 optional suggestions, guarded acceptance and historical records."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.venues.bookings import (
    accept_suggestion,
    create_booking_record,
    reject_booking,
)
from apps.venues.models import BookingStatus, VenueBlock, VenueBooking, VenueBookingHistory
from apps.venues.tests.conftest import make_venue
from conftest import make_event

pytestmark = pytest.mark.django_db
START = datetime(2030, 6, 18, 10, tzinfo=ZoneInfo("Asia/Singapore"))


@pytest.fixture
def rooms():
    return [
        make_venue(name=name, capacity=100, opens_at=time(8), closes_at=time(22))
        for name in ["Original hall", "Suggested hall"]
    ]


@pytest.fixture
def booking(organiser, coordinator, rooms):
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        expected_attendance=60,
        preferred_start=START,
        preferred_end=START + timedelta(hours=2),
    )
    return create_booking_record(
        event=event,
        venue=rooms[0],
        starts_at=START,
        ends_at=START + timedelta(hours=2),
        attendance=60,
        layout="THEATRE",
        required_facilities=["Projector"],
        accessibility_notes="Keep the aisle clear",
        requested_by=coordinator,
    )


def url(booking, action):
    return f"/api/venue-bookings/{booking.pk}/{action}/"


def suggest(api, booking, staff, suggested_room=None, **suggestion):
    api.force_authenticate(staff)
    if suggested_room is not None:
        suggestion["venue"] = suggested_room.pk
    return api.post(
        url(booking, "reject"),
        {"reason": "Original room unavailable", "suggestion": suggestion},
        format="json",
    )


def test_rejection_persists_and_delivers_suggestion_to_coordinator(
    api, booking, rooms, venue_staff, coordinator
):
    response = suggest(api, booking, venue_staff, rooms[1])
    assert response.status_code == 200, response.data
    alternative = response.data["booking"]["suggestion"]
    assert alternative["venue"] == rooms[1].pk
    assert alternative["booking"] is None
    booking.refresh_from_db()
    assert booking.status == BookingStatus.REJECTED
    assert booking.decision_reason == "Original room unavailable"
    assert booking.suggested_starts_at == START
    assert booking.decided_by == venue_staff
    notice = Notification.objects.get(
        recipient=coordinator, event=booking.event, kind=NotificationKind.VENUE_DECIDED
    )
    assert "Suggested hall" in notice.message and "Original room unavailable" in notice.message
    api.force_authenticate(coordinator)
    rows = api.get(f"/api/events/{booking.event_id}/venue-bookings/").data
    assert rows[0]["suggestion"]["venue_name"] == "Suggested hall"
    assert rows[0]["decision_reason"] == "Original room unavailable"
    assert VenueBooking.objects.count() == 1


@pytest.mark.parametrize("kind", ["venue", "time", "both"])
def test_acceptance_uses_suggested_values_inherits_requirements_and_replays_once(
    api, booking, rooms, venue_staff, coordinator, kind
):
    data = {}
    if kind in ("venue", "both"):
        data["venue"] = rooms[1].pk
    if kind in ("time", "both"):
        data.update(starts_at=START + timedelta(hours=3), ends_at=START + timedelta(hours=5))
    response = suggest(api, booking, venue_staff, **data)
    assert response.status_code == 200, response.data
    api.force_authenticate(coordinator)
    first = api.post(url(booking, "accept-suggestion"))
    again = api.post(url(booking, "accept-suggestion"))
    assert first.status_code == again.status_code == 200
    assert first.data["booking"]["id"] == again.data["booking"]["id"]
    created = VenueBooking.objects.get(pk=first.data["booking"]["id"])
    assert created.status == BookingStatus.PENDING
    assert created.venue_id == data.get("venue", booking.venue_id)
    assert created.starts_at == data.get("starts_at", START)
    assert created.ends_at == data.get("ends_at", booking.ends_at)
    assert created.session_id == booking.session_id
    assert created.attendance == 60
    assert created.layout == "THEATRE"
    assert created.required_facilities == ["Projector"]
    assert created.accessibility_notes == "Keep the aisle clear"
    assert created.requested_by == coordinator
    assert (
        Notification.objects.filter(
            event=booking.event, kind=NotificationKind.VENUE_REQUESTED
        ).count()
        == 1
    )
    booking.refresh_from_db()
    assert booking.suggestion_booking_id == created.pk
    assert booking.status == BookingStatus.REJECTED
    assert booking.history.filter(to_status=BookingStatus.REJECTED).count() == 1


@pytest.mark.parametrize("obstruction", ["approved", "held", "block", "out_of_service"])
def test_staff_warned_before_rejection_is_sent(
    api, booking, rooms, venue_staff, organiser, coordinator, obstruction
):
    venue = rooms[1]
    venue.setup_minutes = 15
    venue.save()
    if obstruction == "block":
        VenueBlock.objects.create(
            venue=venue, starts_at=START, ends_at=START + timedelta(hours=1), reason="Maintenance"
        )
    elif obstruction == "out_of_service":
        venue.in_service = False
        venue.save()
    else:
        other = create_booking_record(
            event=make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator),
            venue=venue,
            starts_at=START - timedelta(hours=1),
            ends_at=START,
            attendance=30,
            requested_by=coordinator,
        )
        values = {"status": BookingStatus.APPROVED}
        if obstruction == "held":
            values = {
                "status": BookingStatus.HELD,
                "hold_until": timezone.now() + timedelta(hours=1),
            }
        VenueBooking.objects.filter(pk=other.pk).update(**values)
    response = suggest(api, booking, venue_staff, venue)
    assert response.status_code == 409, response.data
    assert "Choose another venue or time before sending" in response.data["detail"]
    assert response.data["reasons"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.suggested_venue_id is None
    assert not Notification.objects.filter(event=booking.event).exists()


def test_expired_hold_does_not_block_suggestion(
    api, booking, rooms, venue_staff, organiser, coordinator
):
    other = create_booking_record(
        event=make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator),
        venue=rooms[1],
        starts_at=START,
        ends_at=START + timedelta(hours=2),
        attendance=30,
        requested_by=coordinator,
    )
    VenueBooking.objects.filter(pk=other.pk).update(
        status=BookingStatus.HELD, hold_until=timezone.now() - timedelta(seconds=1)
    )
    assert suggest(api, booking, venue_staff, rooms[1]).status_code == 200


@pytest.mark.parametrize(
    "changed", ["occupied", "capacity", "cancelled", "removed", "new_request", "past"]
)
def test_stale_suggestion_is_refused_without_creating_request(
    api, booking, rooms, venue_staff, coordinator, organiser, changed, monkeypatch
):
    assert suggest(api, booking, venue_staff, rooms[1]).status_code == 200
    initial = VenueBooking.objects.count()
    if changed == "occupied":
        VenueBlock.objects.create(
            venue=rooms[1], starts_at=START, ends_at=START + timedelta(hours=1), reason="New block"
        )
    elif changed == "capacity":
        rooms[1].capacity = 10
        rooms[1].save()
    elif changed == "cancelled":
        booking.event.status = EventStatus.CANCELLED
        booking.event.save()
    elif changed == "removed":
        from apps.venues.models import EventSession

        # A real optional breakout session may be removed after its rejection.
        session = EventSession.objects.create(event=booking.event, name="Workshop", kind="BREAKOUT")
        booking.session = session
        booking.save()
        session.is_active = False
        session.save()
    elif changed == "new_request":
        create_booking_record(
            event=booking.event,
            venue=rooms[0],
            starts_at=START,
            ends_at=START + timedelta(hours=2),
            attendance=60,
            requested_by=coordinator,
            session=booking.session,
        )
        initial += 1
    else:
        monkeypatch.setattr(timezone, "now", lambda: START)
    api.force_authenticate(coordinator)
    response = api.post(url(booking, "accept-suggestion"))
    assert response.status_code in (400, 409), response.data
    assert VenueBooking.objects.count() == initial
    booking.refresh_from_db()
    assert booking.suggestion_booking_id is None


@pytest.mark.parametrize(
    "actor_name", ["second_coordinator", "organiser", "venue_staff", "attendee", "lead"]
)
def test_only_assigned_coordinator_can_accept(
    api, booking, rooms, venue_staff, request, actor_name
):
    assert suggest(api, booking, venue_staff, rooms[1]).status_code == 200
    api.force_authenticate(request.getfixturevalue(actor_name))
    assert api.post(url(booking, "accept-suggestion")).status_code == 403
    assert VenueBooking.objects.count() == 1


@pytest.mark.parametrize(
    "suggestion",
    [
        {},
        {"venue": 999999},
        {"starts_at": START.isoformat()},
        {"starts_at": START.isoformat(), "ends_at": START.isoformat()},
    ],
)
def test_invalid_suggestions_leave_request_pending(api, booking, venue_staff, suggestion):
    response = suggest(api, booking, venue_staff, **suggestion)
    assert response.status_code == 400, response.data
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_rejection_without_suggestion_still_works(api, booking, venue_staff, coordinator):
    api.force_authenticate(venue_staff)
    response = api.post(url(booking, "reject"), {"reason": "No space"}, format="json")
    assert response.status_code == 200
    assert response.data["booking"]["suggestion"] is None
    api.force_authenticate(coordinator)
    assert api.post(url(booking, "accept-suggestion")).status_code == 400


def test_notification_failure_rolls_back_rejection_and_suggestion(api, booking, rooms, venue_staff):
    with patch(
        "apps.venues.bookings._notify_coordinator", side_effect=RuntimeError("Write failed")
    ):
        with pytest.raises(RuntimeError, match="Write failed"):
            suggest(api, booking, venue_staff, rooms[1])
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING and booking.suggested_venue_id is None
    assert not VenueBookingHistory.objects.filter(
        booking=booking, to_status=BookingStatus.REJECTED
    ).exists()


def test_database_requires_complete_suggestion(booking, rooms):
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueBooking.objects.filter(pk=booking.pk).update(suggested_venue=rooms[1])


@pytest.mark.django_db(transaction=True)
def test_concurrent_acceptance_creates_one_request(booking, rooms, venue_staff, coordinator):
    reject_booking(booking, venue_staff, "Room unavailable", suggestion={"venue": rooms[1].pk})
    barrier = Barrier(2)

    def accept():
        try:
            barrier.wait(timeout=5)
            return accept_suggestion(booking, coordinator).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(accept) for _ in range(2)]
        ids = [f.result(timeout=15) for f in futures]
    assert ids[0] == ids[1]
    assert VenueBooking.objects.count() == 2


@pytest.mark.parametrize("role_state", ["coordinator", "inactive_staff"])
def test_service_requires_active_venue_staff(booking, venue_staff, coordinator, role_state):
    from apps.venues.bookings import BookingValidationError

    actor = coordinator
    if role_state == "inactive_staff":
        actor = venue_staff
        actor.is_active = False
    with pytest.raises(BookingValidationError):
        reject_booking(booking, actor, "No room")
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_unchanged_and_past_suggestions_are_refused(api, booking, rooms, venue_staff):
    response = suggest(api, booking, venue_staff, rooms[0])
    assert response.status_code == 400
    past = datetime(2020, 6, 18, 10, tzinfo=ZoneInfo("Asia/Singapore"))
    response = suggest(
        api, booking, venue_staff, rooms[1], starts_at=past, ends_at=past + timedelta(hours=1)
    )
    assert response.status_code == 400
    assert "future" in response.data["suggestion"][0]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
