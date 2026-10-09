"""SCRUM-79 (US-20.1) - notified of submissions, decisions and confirmations."""

import pytest

from apps.accounts.models import User
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


@pytest.mark.django_db
def test_ac1_submitting_notifies_the_assigned_coordinator(
    signed_in_organiser, coordinator, organiser
):
    draft = make_event(organiser)

    response = signed_in_organiser.post(f"/api/events/{draft.pk}/submit/")

    assert response.status_code == 200, response.data
    note = Notification.objects.get(recipient=coordinator)
    assert "You have been assigned" in note.message
    assert note.event == draft


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("step", "payload", "kind", "words"),
    [
        ("approve", {}, NotificationKind.APPROVED, "approved"),
        ("reject", {"reason": "Out of scope"}, NotificationKind.REJECTED, "Out of scope"),
        (
            "request-clarification",
            {"message": "What is the budget?"},
            NotificationKind.CLARIFICATION,
            "What is the budget?",
        ),
    ],
)
def test_ac2_the_client_hears_each_decision_and_its_reason(
    signed_in_coordinator, coordinator, organiser, step, payload, kind, words
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)

    response = signed_in_coordinator.post(f"/api/events/{event.pk}/{step}/", payload, format="json")

    assert response.status_code == 200, response.data
    note = Notification.objects.get(recipient=organiser, kind=kind)
    assert words in note.message


@pytest.mark.django_db
@pytest.mark.parametrize("step", ["approve", "reject"])
def test_ac3_the_requesting_coordinator_hears_the_booking_decision(
    signed_in_venue_staff, coordinator, organiser, step
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    booking = book(event, make_venue(), status=BookingStatus.PENDING, requested_by=coordinator)

    signed_in_venue_staff.post(
        f"/api/venue-bookings/{booking.pk}/{step}/", {"reason": "Closed"}, format="json"
    )

    assert Notification.objects.filter(
        recipient=coordinator, kind=NotificationKind.BOOKING_DECIDED
    ).exists()


@pytest.mark.django_db
def test_ac4_confirmation_notifies_client_and_involved_staff(
    signed_in_coordinator, coordinator, organiser, venue_staff, tech_staff
):
    from apps.equipment.models import EquipmentType
    from apps.equipment.tests.conftest import hold

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    book(event, make_venue(), decided_by=venue_staff)
    hold(
        event, EquipmentType.objects.create(name="Mic", total_quantity=2), 1, reserved_by=tech_staff
    )
    bystander = User.objects.create_user(
        username="v2@connectsphere.example",
        email="v2@connectsphere.example",
        password="pw-for-tests-only",
        role="VENUE_STAFF",
    )

    signed_in_coordinator.post(f"/api/events/{event.pk}/confirm/")

    recipients = set(Notification.objects.values_list("recipient__email", flat=True))
    assert {organiser.email, venue_staff.email, tech_staff.email} <= recipients
    assert bystander.email not in recipients


@pytest.mark.django_db
def test_ac5_each_notification_names_the_event_what_happened_and_when(api, coordinator, organiser):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)
    api.post(f"/api/events/{event.pk}/approve/")
    api.force_authenticate(organiser)

    [note] = api.get("/api/notifications/").data

    assert note["event"] == event.pk
    assert note["event_name"] == "Regional Partner Conference"
    assert note["kind_label"] == "Request approved"
    assert note["message"]
    assert note["created_at"]
