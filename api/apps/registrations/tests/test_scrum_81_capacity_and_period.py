"""SCRUM-81 (US-18.3) - registration limited by capacity and registration period."""

import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import Registration, RegistrationStatus
from apps.registrations.services import RegistrationRefused, capacity_of, register
from apps.registrations.tests.conftest import details, fill, make_attendee


def url(event):
    return f"/api/events/{event.pk}/registrations/"


@pytest.mark.django_db
def test_ac1_a_full_event_refuses_and_says_so(as_attendee, event):
    fill(event, 3)

    response = as_attendee.post(url(event), details(), format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "This event is full."
    assert response.data["full"] is True


@pytest.mark.django_db
def test_ac1_capacity_defaults_to_the_expected_attendance(event):
    event.registration_capacity = None

    assert capacity_of(event) == 120


@pytest.mark.django_db
def test_ac2_before_opening_registration_is_refused_with_the_opening_date(as_attendee, event):
    event.registration_opens_at = timezone.now() + timezone.timedelta(days=2)
    event.save()

    response = as_attendee.post(url(event), details(), format="json")

    assert response.status_code == 409
    assert response.data["detail"].startswith("Registration opens on ")
    assert (
        as_attendee.get(f"/api/events/{event.pk}/")
        .data["registration_message"]
        .startswith("Registration opens on ")
    )


@pytest.mark.django_db
def test_ac3_after_closing_registration_is_refused(as_attendee, event):
    event.registration_opens_at = timezone.now() - timezone.timedelta(days=5)
    event.registration_closes_at = timezone.now() - timezone.timedelta(minutes=1)
    event.save()

    response = as_attendee.post(url(event), details(), format="json")

    assert response.data["detail"] == "Registration for this event has closed."


@pytest.mark.django_db
def test_ac3_registration_closes_when_the_event_starts_if_no_date_is_set(as_attendee, event):
    event.preferred_start = timezone.now() - timezone.timedelta(minutes=5)
    event.save()

    response = as_attendee.post(url(event), details(), format="json")

    assert response.data["detail"] == "Registration for this event has closed."


@pytest.mark.django_db(transaction=True)
def test_ac4_two_attendees_racing_for_the_last_place_only_one_gets_it(event):
    fill(event, 2)
    racers = [make_attendee(f"racer{i}@example.com") for i in range(2)]
    results = []
    barrier = threading.Barrier(2)

    def attempt(user):
        try:
            barrier.wait()
            register(event, user, details(email=user.email))
            results.append("ok")
        except RegistrationRefused as exc:
            results.append(exc.detail)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(user,)) for user in racers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["This event is full.", "ok"]
    assert Registration.objects.filter(status=RegistrationStatus.REGISTERED).count() == 3


@pytest.mark.django_db
def test_ac5_taking_the_final_place_notifies_client_and_coordinator(
    as_attendee, organiser, coordinator, event
):
    fill(event, 2)

    as_attendee.post(url(event), details(), format="json")

    for user in (organiser, coordinator):
        note = Notification.objects.get(recipient=user, kind=NotificationKind.EVENT_FULL)
        assert "is full (3 places taken)" in note.message


@pytest.mark.django_db
def test_ac5_no_full_notice_while_places_remain(as_attendee, event):
    as_attendee.post(url(event), details(), format="json")

    assert not Notification.objects.filter(kind=NotificationKind.EVENT_FULL).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"registration_capacity": 0}, "registration_capacity"),
        (
            {
                "registration_opens_at": "2031-01-02T10:00:00+08:00",
                "registration_closes_at": "2031-01-01T10:00:00+08:00",
            },
            "registration_closes_at",
        ),
        ({"registration_closes_at": "2099-01-01T10:00:00+08:00"}, "registration_closes_at"),
    ],
)
def test_the_registration_settings_are_validated(signed_in_coordinator, event, change, field):
    from apps.core.statuses import EventStatus

    event.status = EventStatus.PLANNING
    event.save()

    response = signed_in_coordinator.patch(f"/api/events/{event.pk}/", change, format="json")

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_the_coordinator_can_set_the_registration_settings(signed_in_coordinator, event):
    from apps.core.statuses import EventStatus

    event.status = EventStatus.PLANNING
    event.save()

    response = signed_in_coordinator.patch(
        f"/api/events/{event.pk}/",
        {"registration_capacity": 50, "waitlist_enabled": True},
        format="json",
    )

    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert (event.registration_capacity, event.waitlist_enabled) == (50, True)


@pytest.mark.django_db
def test_an_event_with_no_capacity_at_all_is_unlimited(event):
    from apps.registrations.services import places_left

    event.registration_capacity = None
    event.expected_attendance = None

    assert places_left(event) is None
