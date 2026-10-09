"""SCRUM-67 (US-12.2) - withdraw a venue booking request."""

import pytest

from apps.accounts.models import Role
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book, make_user


def url(booking):
    return f"/api/venue-bookings/{booking.pk}/withdraw/"


@pytest.mark.django_db
def test_ac1_an_undecided_request_is_withdrawn_and_venue_staff_are_told(
    signed_in_coordinator, venue_staff, pending
):
    response = signed_in_coordinator.post(url(pending))

    assert response.status_code == 200
    assert response.data["status"] == BookingStatus.WITHDRAWN
    note = Notification.objects.get(recipient=venue_staff)
    assert note.kind == NotificationKind.BOOKING_WITHDRAWN
    assert "was withdrawn" in note.message


@pytest.mark.django_db
def test_ac2_a_withdrawn_period_is_no_longer_held(signed_in_coordinator, pending, venue):
    period = {"start": pending.start.isoformat(), "end": pending.end.isoformat()}
    before = signed_in_coordinator.get(f"/api/venues/{venue.pk}/availability/", period)

    signed_in_coordinator.post(url(pending))
    after = signed_in_coordinator.get(f"/api/venues/{venue.pk}/availability/", period)

    assert [s["status"] for s in before.data["segments"]] == ["TENTATIVE"]
    assert [s["status"] for s in after.data["segments"]] == ["AVAILABLE"]


@pytest.mark.django_db
def test_ac3_an_approved_booking_needs_confirmation_before_release(signed_in_coordinator, approved):
    warned = signed_in_coordinator.post(url(approved), {}, format="json")

    assert warned.status_code == 409
    assert warned.data["warning"] is True
    assert "releases the confirmed arrangement" in warned.data["detail"]
    approved.refresh_from_db()
    assert approved.status == BookingStatus.APPROVED

    released = signed_in_coordinator.post(url(approved), {"confirm": True}, format="json")

    assert released.status_code == 200
    approved.refresh_from_db()
    assert approved.status == BookingStatus.WITHDRAWN


@pytest.mark.django_db
def test_ac4_who_withdrew_and_when_are_recorded(signed_in_coordinator, coordinator, pending):
    response = signed_in_coordinator.post(url(pending))

    pending.refresh_from_db()
    assert pending.withdrawn_by == coordinator
    assert pending.withdrawn_at is not None
    assert response.data["withdrawn_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [BookingStatus.REJECTED, BookingStatus.WITHDRAWN, BookingStatus.RELEASED]
)
def test_a_closed_request_cannot_be_withdrawn(signed_in_coordinator, event, venue, status):
    closed = book(event, venue, status=status)

    response = signed_in_coordinator.post(url(closed), {"confirm": True}, format="json")

    assert response.status_code == 409


@pytest.mark.django_db
def test_only_the_assigned_coordinator_can_withdraw(api, pending):
    api.force_authenticate(make_user("c2@connectsphere.example", Role.EVENT_COORDINATOR))

    response = api.post(url(pending))

    assert response.status_code == 403
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_venue_staff_cannot_withdraw(signed_in_venue_staff, pending):
    assert signed_in_venue_staff.post(url(pending)).status_code == 403
