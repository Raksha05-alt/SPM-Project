"""SCRUM-67 acceptance and failure cases; approved fixtures use the G02 transition contract."""

from unittest.mock import patch

import pytest
from django.utils.dateparse import parse_datetime

from apps.notifications.models import Notification, NotificationKind
from apps.venues.availability import availability
from apps.venues.bookings import transition_booking, withdraw_booking
from apps.venues.models import BookingStatus
from apps.venues.tests.test_scrum_11_request_booking import (
    END,
    START,
    request_as,
)
from apps.venues.tests.test_scrum_11_request_booking import (
    event as event,
)
from apps.venues.tests.test_scrum_11_request_booking import (
    hall as hall,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def booking(api, coordinator, event, hall):
    response = request_as(api, coordinator, event, hall)
    assert response.status_code == 201
    return event.venue_bookings.get()


def url(booking):
    return f"/api/events/{booking.event_id}/venue-bookings/{booking.pk}/withdraw/"


def test_pending_history_notice_and_repeat(api, coordinator, venue_staff, booking):
    api.force_authenticate(coordinator)
    response = api.post(url(booking), {"expected_status": "PENDING"}, format="json")
    assert response.status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.WITHDRAWN
    change = booking.history.get(to_status=BookingStatus.WITHDRAWN)
    assert change.actor == coordinator
    assert parse_datetime(response.data["booking"]["withdrawn_at"]) == change.changed_at
    assert response.data["booking"]["withdrawn_by_name"] == (
        coordinator.get_full_name() or coordinator.email
    )
    assert (
        Notification.objects.filter(
            recipient=venue_staff, kind=NotificationKind.VENUE_WITHDRAWN
        ).count()
        == 1
    )
    assert api.post(url(booking), {"expected_status": "PENDING"}, format="json").status_code == 409
    assert booking.history.count() == 2
    assert Notification.objects.filter(kind=NotificationKind.VENUE_WITHDRAWN).count() == 1


def test_approved_confirmation_and_fresh_availability(api, coordinator, venue_staff, booking, hall):
    transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    assert availability(hall, START, END)["conflicts"]
    api.force_authenticate(coordinator)
    assert api.post(url(booking), {"expected_status": "APPROVED"}, format="json").status_code == 409
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    response = api.post(
        url(booking), {"expected_status": "APPROVED", "confirm_release": True}, format="json"
    )
    assert response.status_code == 200
    assert availability(hall, START, END)["conflicts"] == []
    booking.refresh_from_db()
    assert booking.decided_by == venue_staff
    assert booking.history.count() == 3


def test_stale_pending_cannot_release_approved(api, coordinator, venue_staff, booking):
    transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    api.force_authenticate(coordinator)
    assert (
        api.post(
            url(booking), {"expected_status": "PENDING", "confirm_release": True}, format="json"
        ).status_code
        == 409
    )
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


def test_reassignment_and_wrong_roles(api, second_coordinator, venue_staff, booking):
    for user in [second_coordinator, venue_staff]:
        api.force_authenticate(user)
        assert (
            api.post(url(booking), {"expected_status": "PENDING"}, format="json").status_code == 403
        )
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_notification_failure_rolls_back(coordinator, booking):
    with patch(
        "apps.notifications.models.Notification.objects.bulk_create",
        side_effect=RuntimeError("failure"),
    ):
        with pytest.raises(RuntimeError):
            withdraw_booking(booking=booking, actor=coordinator, expected_status="PENDING")
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.history.count() == 1


def test_safety_invalidation_is_atomic(coordinator, venue_staff, booking):
    from apps.safety.models import SafetyCheck, SafetyStatus
    from apps.safety.services import arrangement_version

    transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    check = SafetyCheck.objects.create(
        event=booking.event,
        requested_by=coordinator,
        arrangement_version=arrangement_version(booking.event),
    )
    with patch(
        "apps.notifications.models.Notification.objects.bulk_create",
        side_effect=RuntimeError("failure"),
    ):
        with pytest.raises(RuntimeError):
            withdraw_booking(
                booking=booking, actor=coordinator, expected_status="APPROVED", confirm_release=True
            )
    booking.refresh_from_db()
    check.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert check.status == SafetyStatus.PENDING
    withdraw_booking(
        booking=booking, actor=coordinator, expected_status="APPROVED", confirm_release=True
    )
    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED


def test_releasing_one_booking_preserves_another(
    api, coordinator, venue_staff, booking, organiser, hall
):
    import datetime

    from apps.core.statuses import EventStatus
    from apps.venues.bookings import create_booking_record
    from conftest import make_event

    other = create_booking_record(
        requested_by=coordinator,
        event=make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator),
        venue=hall,
        starts_at=END,
        ends_at=END + datetime.timedelta(hours=2),
        attendance=10,
    )
    transition_booking(other, BookingStatus.APPROVED, venue_staff)
    transition_booking(booking, BookingStatus.APPROVED, venue_staff)
    api.force_authenticate(coordinator)
    assert (
        api.post(
            url(booking), {"expected_status": "APPROVED", "confirm_release": True}, format="json"
        ).status_code
        == 200
    )
    other.refresh_from_db()
    assert other.status == BookingStatus.APPROVED
    assert len(availability(hall, END, END + datetime.timedelta(hours=2))["conflicts"]) == 1


def test_rejected_and_closed_events_refuse(api, coordinator, venue_staff, booking):
    from apps.core.statuses import EventStatus

    transition_booking(booking, BookingStatus.REJECTED, venue_staff, "Unavailable")
    api.force_authenticate(coordinator)
    assert api.post(url(booking), {"expected_status": "REJECTED"}, format="json").status_code == 409
    booking.event.status = EventStatus.CANCELLED
    booking.event.save(update_fields=["status"])
    assert api.post(url(booking), {"expected_status": "REJECTED"}, format="json").status_code == 409
    booking.refresh_from_db()
    assert booking.status == BookingStatus.REJECTED
