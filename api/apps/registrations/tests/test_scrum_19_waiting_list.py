"""SCRUM-19 - Join an event waiting list.

As an Attendee, I want to join the waiting list for a full event, so that I
can register if a place becomes available.

FIFO by join time then id, notification only (Sprint 4 guide, Week 2 G3 D15):
a notice never enrols anyone, and registering still needs a fresh capacity
check. Case IDs: S4-19-<case>.
"""

import datetime

import pytest
from django.utils import timezone

from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import (
    Registration,
    RegistrationStatus,
    WaitlistNotice,
)
from apps.registrations.services import (
    AlreadyRegistered,
    RegistrationRefused,
    capacity_of,
    join_waitlist,
    offer_places,
    register,
    set_policy,
    withdraw,
)
from apps.registrations.tests.conftest import details, open_policy
from conftest import _make_user


def waitlist_url(event):
    return f"/api/events/{event.pk}/waitlist/"


def register_url(event):
    return f"/api/events/{event.pk}/registration/"


def offers():
    return Notification.objects.filter(kind=NotificationKind.PLACE_AVAILABLE)


@pytest.fixture
def full_event(confirmed_event, third_attendee):
    """Capacity 1, taken by Cal; the waiting list is on."""
    open_policy(confirmed_event, capacity=1, waitlist_enabled=True)
    register(event=confirmed_event, attendee=third_attendee, **details(third_attendee))
    return confirmed_event


def wait(event, user, **kwargs):
    return join_waitlist(event=event, attendee=user, **details(user), **kwargs)


# S4-19-01 - AC1: a full event with a waiting list adds me and confirms.


@pytest.mark.django_db
def test_s4_19_01_ac1_joining_a_full_events_waiting_list(api, attendee, full_event):
    api.force_authenticate(attendee)

    response = api.post(waitlist_url(full_event), details(attendee), format="json")

    assert response.status_code == 201
    assert response.data["position"] == 1
    entry = Registration.objects.get(attendee=attendee)
    assert entry.status == RegistrationStatus.WAITLISTED
    notice = Notification.objects.get(kind=NotificationKind.WAITLIST_JOINED)
    assert notice.recipient == attendee
    assert "number 1 on the waiting list" in notice.message


@pytest.mark.django_db
def test_s4_19_01_joining_twice_shows_my_existing_place(attendee, full_event):
    first = wait(full_event, attendee)

    with pytest.raises(AlreadyRegistered) as caught:
        wait(full_event, attendee)
    assert caught.value.registration == first


@pytest.mark.django_db
def test_s4_19_01_a_registered_attendee_cannot_also_wait(third_attendee, full_event):
    with pytest.raises(AlreadyRegistered):
        wait(full_event, third_attendee)


@pytest.mark.django_db
def test_s4_19_01_no_waiting_list_when_the_organiser_has_not_enabled_it(attendee, full_event):
    full_event.registration_policy.waitlist_enabled = False
    full_event.registration_policy.save(update_fields=["waitlist_enabled"])

    with pytest.raises(RegistrationRefused) as caught:
        wait(full_event, attendee)
    assert caught.value.code == "no_waitlist"


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["closed", "planning"])
def test_s4_19_01_no_joining_when_registration_is_closed_or_event_not_confirmed(
    attendee, full_event, change
):
    if change == "closed":
        full_event.registration_policy.manually_closed = True
        full_event.registration_policy.save(update_fields=["manually_closed"])
    else:
        full_event.status = "PLANNING"
        full_event.save(update_fields=["status"])

    with pytest.raises(RegistrationRefused) as caught:
        wait(full_event, attendee)
    assert caught.value.code in {"closed", "not_confirmed"}
    assert not Registration.objects.filter(attendee=attendee).exists()


# S4-19-02 - AC2: with places available, no waiting list is offered.


@pytest.mark.django_db
def test_s4_19_02_ac2_places_available_means_no_waiting_list(api, attendee, confirmed_event):
    open_policy(confirmed_event, capacity=5, waitlist_enabled=True)
    api.force_authenticate(attendee)

    summary = api.get(register_url(confirmed_event)).data
    response = api.post(waitlist_url(confirmed_event), details(attendee), format="json")

    assert (summary["open"], summary["waitlist_offered"]) == (True, False)
    assert response.status_code == 409
    assert response.data["code"] == "places_available"


@pytest.mark.django_db
def test_s4_19_02_a_full_event_offers_the_waiting_list(api, attendee, full_event):
    api.force_authenticate(attendee)

    summary = api.get(register_url(full_event)).data

    assert (summary["reason_code"], summary["waitlist_offered"]) == ("full", True)


# S4-19-03 - AC3: my waiting-list status and position are shown.


@pytest.mark.django_db
def test_s4_19_03_ac3_my_waiting_status_and_position(api, attendee, second_attendee, full_event):
    wait(full_event, second_attendee)
    wait(full_event, attendee)
    api.force_authenticate(attendee)

    summary = api.get(register_url(full_event)).data
    mine = api.get("/api/registrations/mine/").data

    assert (summary["my_status"], summary["waitlist_position"]) == (
        RegistrationStatus.WAITLISTED,
        2,
    )
    assert summary["waitlist_offered"] is False
    assert [(r["status"], r["status_label"]) for r in mine] == [
        (RegistrationStatus.WAITLISTED, "On the waiting list")
    ]


# S4-19-04 - AC4: waiting attendees are not counted as registered.


@pytest.mark.django_db
def test_s4_19_04_ac4_waiting_attendees_are_not_counted(
    api, attendee, second_attendee, full_event, coordinator
):
    wait(full_event, attendee)
    wait(full_event, second_attendee)
    api.force_authenticate(coordinator)

    data = api.get(f"/api/events/{full_event.pk}/registrations/").data
    policy = api.get(f"/api/events/{full_event.pk}/registration-policy/").data

    assert (data["registered"], data["waiting"]) == (1, 2)
    assert (policy["registered"], policy["waiting"]) == (1, 2)
    assert capacity_of(full_event).registered == 1


# S4-19-05 - AC5: a place opens, the waiting list is processed, FIFO notice.


@pytest.mark.django_db
def test_s4_19_05_ac5_a_withdrawal_notifies_the_first_in_line(
    attendee, second_attendee, third_attendee, full_event
):
    wait(full_event, attendee)
    wait(full_event, second_attendee)
    taken = Registration.objects.get(attendee=third_attendee)

    withdraw(registration=taken, actor=third_attendee, confirm=True)

    assert list(offers().values_list("recipient_id", flat=True)) == [attendee.pk]
    assert "A place has become available" in offers().get().message
    assert WaitlistNotice.objects.get().entry.attendee == attendee
    # A notice reserves nothing: the attendee is still waiting until they register.
    assert Registration.objects.get(attendee=attendee).status == RegistrationStatus.WAITLISTED
    assert capacity_of(full_event).registered == 0


@pytest.mark.django_db
def test_s4_19_05_fifo_uses_join_time_then_id(full_event):
    same_moment = timezone.now()
    people = [
        _make_user(f"w{n}@example.com", "ATTENDEE", None, f"W{n}", "Waiter") for n in range(3)
    ]
    entries = [wait(full_event, person, now=same_moment) for person in people]
    full_event.registration_policy.capacity = 3  # two places open at once
    full_event.registration_policy.save(update_fields=["capacity"])

    notified = offer_places(full_event, "test-release:1")

    assert notified == entries[:2]


@pytest.mark.django_db
def test_s4_19_05_processing_the_same_release_again_notifies_nobody_twice(
    attendee, third_attendee, full_event
):
    wait(full_event, attendee)
    taken = Registration.objects.get(attendee=third_attendee)
    withdraw(registration=taken, actor=third_attendee, confirm=True)
    occurrence = WaitlistNotice.objects.get().occurrence

    assert offer_places(full_event, occurrence) == []
    assert offers().count() == 1


@pytest.mark.django_db
def test_s4_19_05_the_notified_attendee_registers_with_a_fresh_check(
    api, attendee, second_attendee, third_attendee, full_event
):
    wait(full_event, attendee)
    withdraw(
        registration=Registration.objects.get(attendee=third_attendee),
        actor=third_attendee,
        confirm=True,
    )
    # Someone not on the list takes the place first: places are not held.
    register(event=full_event, attendee=second_attendee, **details(second_attendee))
    with pytest.raises(RegistrationRefused) as caught:
        register(event=full_event, attendee=attendee, **details(attendee))
    assert caught.value.code == "full"

    # A later release lets the waiting attendee register through their own entry.
    withdraw(
        registration=Registration.objects.get(attendee=second_attendee),
        actor=second_attendee,
        confirm=True,
    )
    api.force_authenticate(attendee)
    response = api.post(register_url(full_event), details(attendee), format="json")

    assert response.status_code == 201
    entry = Registration.objects.get(attendee=attendee)
    assert entry.status == RegistrationStatus.REGISTERED
    assert [h.to_status for h in entry.history.order_by("pk")] == [
        RegistrationStatus.WAITLISTED,
        RegistrationStatus.REGISTERED,
    ]
    assert offers().filter(recipient=attendee).count() == 2


@pytest.mark.django_db
def test_s4_19_05_raising_the_capacity_processes_the_waiting_list(
    organiser, attendee, second_attendee, full_event
):
    wait(full_event, attendee)
    wait(full_event, second_attendee)

    set_policy(event=full_event, actor=organiser, capacity=2)

    assert list(offers().values_list("recipient_id", flat=True)) == [attendee.pk]


@pytest.mark.django_db
def test_s4_19_05_no_offers_while_the_event_is_back_in_planning(
    attendee, third_attendee, full_event
):
    wait(full_event, attendee)
    full_event.status = "PLANNING"
    full_event.save(update_fields=["status"])

    withdraw(
        registration=Registration.objects.get(attendee=third_attendee),
        actor=third_attendee,
        confirm=True,
    )

    assert not offers().exists()


@pytest.mark.django_db
def test_s4_19_05_leaving_the_waiting_list_releases_no_place(
    attendee, second_attendee, third_attendee, full_event
):
    entry = wait(full_event, attendee)
    wait(full_event, second_attendee)

    withdraw(registration=entry, actor=attendee, confirm=True)

    assert not offers().exists()
    assert capacity_of(full_event).registered == 1
    assert (
        "waiting-list place"
        in Notification.objects.get(kind=NotificationKind.REG_WITHDRAWN).message
    )


@pytest.mark.django_db
def test_s4_19_06_the_organiser_turns_the_waiting_list_on(signed_in_organiser, confirmed_event):
    response = signed_in_organiser.put(
        f"/api/events/{confirmed_event.pk}/registration-policy/",
        {"enabled": True, "capacity": 10, "waitlist_enabled": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["waitlist_enabled"] is True
    assert confirmed_event.registration_policy.changes.first().after["waitlist_enabled"] is True


@pytest.mark.django_db
def test_s4_19_06_only_attendees_join_a_waiting_list(organiser, full_event):
    with pytest.raises(RegistrationRefused) as caught:
        wait(full_event, organiser)
    assert caught.value.code == "not_attendee"


@pytest.mark.django_db
def test_s4_19_06_offers_stop_once_registration_closes(attendee, third_attendee, full_event):
    wait(full_event, attendee)
    policy = full_event.registration_policy
    policy.closes_at = timezone.now() - datetime.timedelta(seconds=1)
    policy.opens_at = timezone.now() - datetime.timedelta(days=1)
    policy.save(update_fields=["closes_at", "opens_at"])

    withdraw(
        registration=Registration.objects.get(attendee=third_attendee),
        actor=third_attendee,
        confirm=True,
    )

    assert not offers().exists()


# S4-19-07 - API refusals and edge cases.


@pytest.mark.django_db
def test_s4_19_07_joining_via_the_api_needs_the_required_details(api, attendee, full_event):
    api.force_authenticate(attendee)

    response = api.post(waitlist_url(full_event), details(attendee, email=""), format="json")

    assert response.status_code == 400
    assert response.data["missing"] == ["email"]
    assert not Registration.objects.filter(attendee=attendee).exists()


@pytest.mark.django_db
def test_s4_19_07_joining_twice_via_the_api_shows_the_existing_place(api, attendee, full_event):
    wait(full_event, attendee)
    api.force_authenticate(attendee)

    response = api.post(waitlist_url(full_event), details(attendee), format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "You are already on the waiting list for this event."
    assert response.data["registration"]["status"] == RegistrationStatus.WAITLISTED


@pytest.mark.django_db
def test_s4_19_07_the_waiting_list_url_only_accepts_joining(api, attendee, full_event):
    api.force_authenticate(attendee)

    assert api.get(waitlist_url(full_event)).status_code == 405


@pytest.mark.django_db
def test_s4_19_07_nothing_is_offered_while_the_event_is_still_full(attendee, full_event):
    entry = wait(full_event, attendee)

    assert offer_places(full_event, "test-release:full") == []
    assert not offers().exists()
    assert str(WaitlistNotice(entry=entry, occurrence="x"))
