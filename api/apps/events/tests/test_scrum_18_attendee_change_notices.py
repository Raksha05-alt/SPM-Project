"""SCRUM-18 (US-20.2) - registered attendees are told when a confirmed event changes."""

import pytest

from apps.core.statuses import EventStatus
from apps.events.tests.change_helpers import HOUR, confirmed_event, iso
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import RegistrationStatus
from apps.registrations.tests.conftest import enrol, make_attendee
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


def move(client, event):
    return client.patch(
        f"/api/events/{event.pk}/",
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
        format="json",
    )


@pytest.mark.django_db
def test_ac1_a_new_date_or_time_notifies_registered_attendees(signed_in_coordinator, setup):
    event, _, _, attendee = setup

    move(signed_in_coordinator, event)

    note = Notification.objects.get(recipient=attendee)
    assert note.kind == NotificationKind.EVENT_CHANGED


@pytest.mark.django_db
def test_ac1_a_new_venue_notifies_registered_attendees(api, venue_staff, setup):
    event, _, _, attendee = setup
    second = book(event, make_venue(name="Riverside Room"), status=BookingStatus.PENDING)
    api.force_authenticate(venue_staff)

    api.post(f"/api/venue-bookings/{second.pk}/approve/")

    note = Notification.objects.get(recipient=attendee)
    assert "The venue for" in note.message and "Riverside Room" in note.message


@pytest.mark.django_db
def test_ac2_the_notice_shows_the_updated_details(signed_in_coordinator, setup):
    event, _, _, attendee = setup

    move(signed_in_coordinator, event)

    event.refresh_from_db()
    message = Notification.objects.get(recipient=attendee).message
    assert "It now runs from" in message
    assert "at Harbour Hall" in message


@pytest.mark.django_db
def test_ac3_only_attendees_of_this_event_are_told(signed_in_coordinator, organiser, setup):
    event, _, _, attendee = setup
    elsewhere = make_event(organiser, status=EventStatus.CONFIRMED, name="Other")
    outsider = make_attendee("outsider@example.com")
    enrol(elsewhere, outsider)

    move(signed_in_coordinator, event)

    assert not Notification.objects.filter(recipient=outsider).exists()


@pytest.mark.django_db
def test_ac4_withdrawn_attendees_are_not_told(signed_in_coordinator, setup):
    event = setup[0]
    gone = make_attendee("gone@example.com")
    enrol(event, gone, status=RegistrationStatus.WITHDRAWN)

    move(signed_in_coordinator, event)

    assert not Notification.objects.filter(recipient=gone).exists()


@pytest.mark.django_db
def test_ac5_a_cancellation_notifies_registered_attendees(signed_in_coordinator, setup):
    event, _, _, attendee = setup

    signed_in_coordinator.post(
        f"/api/events/{event.pk}/cancel/", {"reason": "Venue flooded"}, format="json"
    )

    message = Notification.objects.get(recipient=attendee).message
    assert "has been cancelled" in message and "Reason: Venue flooded" in message


@pytest.mark.django_db
def test_ac5_a_cancellation_without_a_reason_still_notifies(signed_in_organiser, setup):
    event, _, _, attendee = setup

    signed_in_organiser.post(f"/api/events/{event.pk}/cancel/", {}, format="json")

    assert Notification.objects.get(recipient=attendee).message.endswith("has been cancelled.")


@pytest.mark.django_db
def test_a_planning_event_changing_time_sends_no_attendee_notice(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    attendee = make_attendee("early@example.com")
    enrol(event, attendee)

    move(signed_in_coordinator, event)

    assert not Notification.objects.filter(recipient=attendee).exists()
