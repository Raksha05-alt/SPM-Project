"""SCRUM-72 (US-13.1) - Venue Staff respond to a venue booking request."""

import pytest

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import block, book, make_user


def url(booking, step=""):
    return f"/api/venue-bookings/{booking.pk}/{step}"


@pytest.mark.django_db
def test_ac1_staff_see_the_event_timing_and_requirements(signed_in_venue_staff, pending):
    pending.layout = "THEATRE"
    pending.facilities = ["Projector"]
    pending.accessibility_needs = "Step-free access"
    pending.save()

    response = signed_in_venue_staff.get(url(pending))

    assert response.status_code == 200
    data = response.data
    assert data["event_name"] == "Regional Partner Conference"
    assert data["start"] and data["end"]
    assert (data["attendance"], data["layout_label"]) == (100, "Theatre")
    assert data["facilities"] == ["Projector"]
    assert data["accessibility_needs"] == "Step-free access"


@pytest.mark.django_db
def test_ac1_staff_can_list_the_pending_requests(signed_in_venue_staff, pending, approved):
    response = signed_in_venue_staff.get("/api/venue-bookings/", {"status": "PENDING"})

    assert [row["id"] for row in response.data] == [pending.pk]


@pytest.mark.django_db
def test_ac2_approving_confirms_the_period_and_notifies_the_coordinator(
    signed_in_venue_staff, coordinator, pending
):
    response = signed_in_venue_staff.post(url(pending, "approve/"))

    assert response.status_code == 200
    assert response.data["status"] == BookingStatus.APPROVED
    pending.refresh_from_db()
    assert pending.status == BookingStatus.APPROVED
    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.BOOKING_DECIDED)
    assert "Harbour Hall is confirmed" in note.message


@pytest.mark.django_db
def test_ac2_an_approved_booking_shows_as_confirmed_in_availability(
    signed_in_venue_staff, pending, venue
):
    signed_in_venue_staff.post(url(pending, "approve/"))

    response = signed_in_venue_staff.get(
        f"/api/venues/{venue.pk}/availability/",
        {"start": pending.start.isoformat(), "end": pending.end.isoformat()},
    )

    assert [piece["status"] for piece in response.data["segments"]] == ["CONFIRMED"]


@pytest.mark.django_db
def test_ac3_rejecting_records_the_reason_and_notifies_coordinator_and_client(
    signed_in_venue_staff, coordinator, organiser, pending
):
    response = signed_in_venue_staff.post(
        url(pending, "reject/"), {"reason": "Hall is being refurbished"}, format="json"
    )

    assert response.status_code == 200
    pending.refresh_from_db()
    assert pending.status == BookingStatus.REJECTED
    assert pending.rejection_reason == "Hall is being refurbished"
    to_coordinator = Notification.objects.get(recipient=coordinator)
    assert "Reason: Hall is being refurbished" in to_coordinator.message
    to_client = Notification.objects.get(recipient=organiser)
    assert "unavailable: Hall is being refurbished" in to_client.message


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": "   "}])
def test_ac4_a_rejection_without_a_reason_is_blocked(signed_in_venue_staff, pending, payload):
    response = signed_in_venue_staff.post(url(pending, "reject/"), payload, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "Enter a reason before rejecting this request."
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING
    assert not Notification.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [BookingStatus.APPROVED, BookingStatus.REJECTED, BookingStatus.WITHDRAWN]
)
@pytest.mark.parametrize("step", ["approve/", "reject/"])
def test_ac5_a_decided_request_cannot_be_decided_again(
    signed_in_venue_staff, event, venue, status, step
):
    decided = book(event, venue, status=status)

    response = signed_in_venue_staff.post(url(decided, step), {"reason": "x"}, format="json")

    assert response.status_code == 409
    assert "already been" in response.data["detail"]
    decided.refresh_from_db()
    assert decided.status == status


@pytest.mark.django_db
@pytest.mark.parametrize("step", ["approve/", "reject/"])
def test_ac6_the_deciding_user_and_time_are_stored(
    signed_in_venue_staff, venue_staff, pending, step
):
    response = signed_in_venue_staff.post(url(pending, step), {"reason": "Full"}, format="json")

    pending.refresh_from_db()
    assert pending.decided_by == venue_staff
    assert pending.decided_at is not None
    assert response.data["decided_by_name"] == "Vera Venue"
    assert AuditLog.objects.filter(action=f"POST {url(pending, step)}", allowed=True).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("step", ["approve/", "reject/"])
def test_only_venue_staff_decide(signed_in_coordinator, pending, step):
    response = signed_in_coordinator.post(url(pending, step), {"reason": "x"}, format="json")

    assert response.status_code == 403
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_technical_staff_cannot_see_venue_bookings(api, pending):
    api.force_authenticate(make_user("t@connectsphere.example", Role.TECHNICAL_SUPPORT))

    assert api.get(url(pending)).status_code == 403


@pytest.mark.django_db
def test_approval_is_refused_while_the_venue_is_blocked(signed_in_venue_staff, pending, venue):
    block(venue, pending.start, pending.end, reason="Flooding")

    response = signed_in_venue_staff.post(url(pending, "approve/"))

    assert response.status_code == 409
    assert "Flooding" in response.data["detail"]
