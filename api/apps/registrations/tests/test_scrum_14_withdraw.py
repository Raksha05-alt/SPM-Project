"""SCRUM-14 (US-18.2) - withdraw from an event registration."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import RegistrationStatus
from apps.registrations.services import places_left
from apps.registrations.tests.conftest import details, enrol, fill, make_attendee


def url(registration):
    return f"/api/registrations/{registration.pk}/withdraw/"


@pytest.mark.django_db
def test_ac1_a_summary_is_shown_then_confirming_withdraws(as_attendee, attendee, event):
    mine = enrol(event, attendee)

    summary = as_attendee.post(url(mine), {}, format="json")

    assert summary.status_code == 409
    assert summary.data["summary"]["event"] == "Regional Partner Conference"
    assert summary.data["summary"]["status"] == "Registered"
    mine.refresh_from_db()
    assert mine.status == RegistrationStatus.REGISTERED

    done = as_attendee.post(url(mine), {"confirm": True}, format="json")

    assert done.status_code == 200
    assert done.data["status_display"] == "Withdrawn"
    note = Notification.objects.get(recipient=attendee)
    assert note.kind == NotificationKind.UNREGISTERED


@pytest.mark.django_db
def test_ac2_the_count_drops_and_the_place_is_free_for_someone_else(as_attendee, attendee, event):
    fill(event, 2)
    mine = enrol(event, attendee)
    assert places_left(event) == 0

    as_attendee.post(url(mine), {"confirm": True}, format="json")

    assert places_left(event) == 1
    as_attendee.force_authenticate(make_attendee("next@example.com"))
    assert (
        as_attendee.post(
            f"/api/events/{event.pk}/registrations/", details(), format="json"
        ).status_code
        == 201
    )


@pytest.mark.django_db
def test_ac3_a_withdrawn_attendee_can_register_again(as_attendee, attendee, event):
    mine = enrol(event, attendee)
    as_attendee.post(url(mine), {"confirm": True}, format="json")

    response = as_attendee.post(f"/api/events/{event.pk}/registrations/", details(), format="json")

    assert response.status_code == 201
    assert event.registrations.filter(attendee=attendee).count() == 2


@pytest.mark.django_db
def test_ac4_withdrawing_after_the_event_has_taken_place_is_refused(as_attendee, attendee, event):
    mine = enrol(event, attendee)
    event.preferred_start = timezone.now() - timezone.timedelta(days=1, hours=6)
    event.preferred_end = timezone.now() - timezone.timedelta(days=1)
    event.save()

    response = as_attendee.post(url(mine), {"confirm": True}, format="json")

    assert response.status_code == 409
    assert "already taken place" in response.data["detail"]


@pytest.mark.django_db
def test_ac4_a_completed_event_cannot_be_withdrawn_from(as_attendee, attendee, event):
    mine = enrol(event, attendee)
    event.status = EventStatus.COMPLETED
    event.save()

    assert as_attendee.post(url(mine), {"confirm": True}, format="json").status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["signed_in_organiser", "signed_in_coordinator"])
def test_ac5_withdrawn_registrations_stay_on_record_for_client_and_coordinator(
    request, as_attendee, attendee, event, fixture
):
    mine = enrol(event, attendee)
    as_attendee.post(url(mine), {"confirm": True}, format="json")
    client = request.getfixturevalue(fixture)

    data = client.get(f"/api/events/{event.pk}/registrations/").data

    assert [(r["full_name"], r["status_display"]) for r in data["registrations"]] == [
        ("Andy Attendee", "Withdrawn")
    ]
    assert data["registered_count"] == 0


@pytest.mark.django_db
def test_ac6_another_attendee_cannot_withdraw_my_registration(api, attendee, event):
    mine = enrol(event, attendee)
    api.force_authenticate(make_attendee("intruder@example.com"))

    response = api.post(url(mine), {"confirm": True}, format="json")

    assert response.status_code == 403
    mine.refresh_from_db()
    assert mine.status == RegistrationStatus.REGISTERED


@pytest.mark.django_db
def test_withdrawing_twice_is_refused(as_attendee, attendee, event):
    mine = enrol(event, attendee)
    as_attendee.post(url(mine), {"confirm": True}, format="json")

    assert as_attendee.post(url(mine), {"confirm": True}, format="json").status_code == 409


@pytest.mark.django_db
def test_registrations_are_private_to_client_and_assigned_coordinator(api, event, other_organiser):
    from apps.venues.tests.helpers import make_user

    api.force_authenticate(other_organiser)
    assert api.get(f"/api/events/{event.pk}/registrations/").status_code == 403
    api.force_authenticate(make_user("c9@connectsphere.example", "COORDINATOR"))
    assert api.get(f"/api/events/{event.pk}/registrations/").status_code == 403
