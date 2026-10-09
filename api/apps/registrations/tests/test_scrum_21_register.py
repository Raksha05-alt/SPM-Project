"""SCRUM-21 (US-18.1) - register for an event."""

import pytest

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import Registration, RegistrationStatus
from apps.registrations.tests.conftest import details, enrol
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


def url(event):
    return f"/api/events/{event.pk}/registrations/"


@pytest.mark.django_db
def test_ac1_registering_records_the_place_and_confirms_it(as_attendee, attendee, event):
    response = as_attendee.post(
        url(event), details(accessibility_needs="Wheelchair space"), format="json"
    )

    assert response.status_code == 201, response.data
    registration = Registration.objects.get()
    assert (registration.attendee, registration.status) == (attendee, RegistrationStatus.REGISTERED)
    assert registration.accessibility_needs == "Wheelchair space"
    assert registration.registered_at is not None
    note = Notification.objects.get(recipient=attendee)
    assert note.kind == NotificationKind.REGISTERED
    assert "You are registered" in note.message


@pytest.mark.django_db
def test_ac2_missing_information_is_identified(as_attendee, event):
    response = as_attendee.post(url(event), {}, format="json")

    assert response.status_code == 400
    assert response.data == {
        "full_name": ["Enter your full name."],
        "email": ["Enter your email address."],
    }
    assert not Registration.objects.exists()


@pytest.mark.django_db
def test_ac2_an_invalid_email_is_identified(as_attendee, event):
    response = as_attendee.post(url(event), details(email="nope"), format="json")

    assert response.data == {"email": ["Enter a valid email address."]}


@pytest.mark.django_db
def test_ac3_registering_twice_is_refused_and_shows_the_existing_registration(
    as_attendee, attendee, event
):
    existing = enrol(event, attendee)

    response = as_attendee.post(url(event), details(), format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "You are already registered for this event."
    assert response.data["existing"] == existing.pk
    assert Registration.objects.count() == 1


@pytest.mark.django_db
def test_ac4_my_events_show_status_and_the_confirmed_date_time_and_venue(
    as_attendee, attendee, event
):
    book(event, make_venue(location="Level 3, Tower A"))
    enrol(event, attendee)

    [row] = as_attendee.get("/api/registrations/").data

    assert row["event_name"] == "Regional Partner Conference"
    assert row["status_display"] == "Registered"
    assert row["event_start"] and row["event_end"]
    assert row["venues"][0]["name"] == "Harbour Hall"
    assert row["venues"][0]["location"] == "Level 3, Tower A"


@pytest.mark.django_db
def test_ac4_an_attendee_sees_only_their_own_registrations(as_attendee, event):
    from apps.registrations.tests.conftest import make_attendee

    other = enrol(event, make_attendee("someone@example.com"))

    assert as_attendee.get("/api/registrations/").data == []
    assert as_attendee.get(f"/api/registrations/{other.pk}/").status_code == 403


@pytest.mark.django_db
def test_ac4_an_attendee_can_open_their_own_registration(as_attendee, attendee, event):
    mine = enrol(event, attendee)

    assert as_attendee.get(f"/api/registrations/{mine.pk}/").data["id"] == mine.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.SUBMITTED, EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CANCELLED],
)
def test_ac5_an_event_that_is_not_confirmed_refuses_registration(
    as_attendee, organiser, coordinator, status
):
    event = make_event(
        organiser, status=status, coordinator=coordinator, registration_required=True
    )

    response = as_attendee.post(url(event), details(), format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "Registration is only possible for confirmed events."


@pytest.mark.django_db
def test_an_event_without_registration_refuses_it(as_attendee, event):
    event.registration_required = False
    event.save()

    response = as_attendee.post(url(event), details(), format="json")

    assert response.data["detail"] == "This event does not take registrations."


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["signed_in_organiser", "signed_in_coordinator"])
def test_only_attendees_register(request, fixture, event):
    client = request.getfixturevalue(fixture)

    assert client.post(url(event), details(), format="json").status_code == 403


@pytest.mark.django_db
def test_the_event_shows_the_attendee_their_registration(as_attendee, attendee, event):
    enrol(event, attendee)

    data = as_attendee.get(f"/api/events/{event.pk}/").data

    assert data["my_registration"]["status_display"] == "Registered"
    assert data["places_left"] == 2
    assert data["registration_message"] is None


@pytest.mark.django_db
def test_the_event_shows_no_places_when_registration_is_off(as_attendee, event):
    event.registration_required = False
    event.save()

    data = as_attendee.get(f"/api/events/{event.pk}/").data

    assert data["places_left"] is None
    assert data["my_registration"] is None


@pytest.mark.django_db
def test_a_cancelled_event_shows_no_venue_in_my_events(as_attendee, attendee, event):
    book(event, make_venue())
    registration = enrol(event, attendee)
    event.status = EventStatus.CANCELLED
    event.save()

    [row] = as_attendee.get("/api/registrations/").data

    assert row["venues"] == []
    assert str(registration) == f"Andy Attendee for event {event.pk} (Registered)"
