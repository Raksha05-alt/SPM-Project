"""SCRUM-19 (US-18.4) - join an event waiting list."""

import pytest

from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import RegistrationStatus
from apps.registrations.tests.conftest import details, enrol, fill, make_attendee


def url(event):
    return f"/api/events/{event.pk}/waitlist/"


@pytest.fixture
def full_event(event):
    event.waitlist_enabled = True
    event.save()
    fill(event, 3)
    return event


@pytest.mark.django_db
def test_ac1_joining_the_waiting_list_of_a_full_event_is_confirmed(
    as_attendee, attendee, full_event
):
    response = as_attendee.post(url(full_event), details(), format="json")

    assert response.status_code == 201, response.data
    assert response.data["status_display"] == "On waiting list"
    note = Notification.objects.get(recipient=attendee)
    assert note.kind == NotificationKind.WAITLISTED


@pytest.mark.django_db
def test_ac1_a_full_event_points_to_its_waiting_list(as_attendee, full_event):
    response = as_attendee.post(
        f"/api/events/{full_event.pk}/registrations/", details(), format="json"
    )

    assert response.data["waitlist_offered"] is True


@pytest.mark.django_db
def test_ac1_an_event_without_a_waiting_list_cannot_be_joined(as_attendee, event):
    fill(event, 3)

    response = as_attendee.post(url(event), details(), format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "This event does not have a waiting list."


@pytest.mark.django_db
def test_ac2_with_places_left_the_waiting_list_is_not_offered(as_attendee, event):
    event.waitlist_enabled = True
    event.save()

    joined = as_attendee.post(url(event), details(), format="json")
    shown = as_attendee.get(f"/api/events/{event.pk}/").data

    assert joined.status_code == 409
    assert joined.data["detail"] == "Places are still available; register instead."
    assert shown["waitlist_offered"] is False


@pytest.mark.django_db
def test_ac3_my_waiting_list_status_is_shown(as_attendee, full_event):
    as_attendee.post(url(full_event), details(), format="json")

    data = as_attendee.get(f"/api/events/{full_event.pk}/").data

    assert data["my_registration"]["status_display"] == "On waiting list"
    assert data["waitlist_offered"] is True


@pytest.mark.django_db
def test_ac3_joining_twice_is_refused(as_attendee, attendee, full_event):
    enrol(full_event, attendee, status=RegistrationStatus.WAITLISTED)

    response = as_attendee.post(url(full_event), details(), format="json")

    assert response.status_code == 409
    assert "already on waiting list" in response.data["detail"]


@pytest.mark.django_db
def test_ac4_waiting_attendees_are_not_counted_as_registered(api, attendee, organiser, full_event):
    api.force_authenticate(attendee)
    api.post(url(full_event), details(), format="json")
    api.force_authenticate(organiser)

    data = api.get(f"/api/events/{full_event.pk}/registrations/").data

    assert (data["registered_count"], data["waitlist_count"], data["places_left"]) == (3, 1, 0)


@pytest.mark.django_db
def test_ac5_a_freed_place_is_offered_to_the_first_waiting_attendee(api, full_event):
    first = enrol(
        full_event, make_attendee("first@example.com"), status=RegistrationStatus.WAITLISTED
    )
    second = enrol(
        full_event, make_attendee("second@example.com"), status=RegistrationStatus.WAITLISTED
    )
    leaver = full_event.registrations.filter(status=RegistrationStatus.REGISTERED).first()
    api.force_authenticate(leaver.attendee)

    api.post(f"/api/registrations/{leaver.pk}/withdraw/", {"confirm": True}, format="json")

    offers = Notification.objects.filter(kind=NotificationKind.PLACE_AVAILABLE)
    assert [n.recipient for n in offers] == [first.attendee]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.place_offered_at is not None
    assert second.place_offered_at is None


@pytest.mark.django_db
def test_ac5_the_waiting_attendee_can_then_take_the_place(api, full_event):
    waiting_user = make_attendee("first@example.com")
    waiting = enrol(full_event, waiting_user, status=RegistrationStatus.WAITLISTED)
    leaver = full_event.registrations.filter(status=RegistrationStatus.REGISTERED).first()
    api.force_authenticate(leaver.attendee)
    api.post(f"/api/registrations/{leaver.pk}/withdraw/", {"confirm": True}, format="json")
    api.force_authenticate(waiting_user)

    response = api.post(
        f"/api/events/{full_event.pk}/registrations/",
        details(email="first@example.com"),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["id"] == waiting.pk
    assert response.data["status_display"] == "Registered"


@pytest.mark.django_db
def test_leaving_the_waiting_list_frees_no_place(api, full_event):
    waiting_user = make_attendee("w@example.com")
    waiting = enrol(full_event, waiting_user, status=RegistrationStatus.WAITLISTED)
    api.force_authenticate(waiting_user)

    api.post(f"/api/registrations/{waiting.pk}/withdraw/", {"confirm": True}, format="json")

    assert not Notification.objects.filter(kind=NotificationKind.PLACE_AVAILABLE).exists()


@pytest.mark.django_db
def test_waiting_lists_respect_the_registration_window(as_attendee, full_event):
    full_event.registration_required = False
    full_event.save()

    assert as_attendee.post(url(full_event), details(), format="json").status_code == 409


@pytest.mark.django_db
def test_no_offers_are_made_while_the_event_is_full(full_event):
    from apps.registrations.services import offer_places

    enrol(full_event, make_attendee("w@example.com"), status=RegistrationStatus.WAITLISTED)

    assert offer_places(full_event) == []
