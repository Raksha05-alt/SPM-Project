"""SCRUM-81 - Registration limited by capacity and registration period.

As ConnectSphere, I want registration to respect the event's capacity and its
registration period, so that events are not over-subscribed and registration
does not stay open indefinitely.

Period semantics (Sprint 4 guide): open while ``opens_at <= now < closes_at``,
plus manual closure. Case IDs: S4-81-<case>.
"""

import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import (
    Registration,
    RegistrationPolicy,
    RegistrationPolicyChange,
    RegistrationStatus,
)
from apps.registrations.services import (
    RegistrationRefused,
    capacity_of,
    register,
    window_problem,
)
from apps.registrations.tests.conftest import details, open_policy

NOW = timezone.now().replace(microsecond=0)


def register_url(event):
    return f"/api/events/{event.pk}/registration/"


def policy_url(event):
    return f"/api/events/{event.pk}/registration-policy/"


def full_notices():
    return Notification.objects.filter(kind=NotificationKind.REGISTRATION_FULL)


# S4-81-01 - AC1: a full event refuses and says so.


@pytest.mark.django_db
def test_s4_81_01_ac1_a_full_event_refuses_and_says_it_is_full(
    api, attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event, capacity=1)
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))
    api.force_authenticate(attendee)

    response = api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "full"
    assert response.data["detail"] == "This event is full."
    assert Registration.objects.filter(attendee=attendee).count() == 0
    assert api.get(register_url(confirmed_event)).data["reason"] == "This event is full."


@pytest.mark.django_db
def test_s4_81_01_capacity_counts_only_active_registrations(
    attendee, second_attendee, confirmed_event
):
    policy = open_policy(confirmed_event, capacity=1)
    withdrawn = register(
        event=confirmed_event, attendee=second_attendee, **details(second_attendee)
    )
    Registration.objects.filter(pk=withdrawn.pk).update(status=RegistrationStatus.WITHDRAWN)

    assert capacity_of(confirmed_event, policy).remaining == 1
    register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert capacity_of(confirmed_event, policy).full is True


@pytest.mark.django_db
def test_s4_81_01_the_cap_is_separate_from_venue_capacity_and_attendance(attendee, confirmed_event):
    # Expected attendance is 120 (make_event); the organiser's cap is 2.
    policy = open_policy(confirmed_event, capacity=2)

    assert capacity_of(confirmed_event, policy).capacity == 2
    assert confirmed_event.expected_attendance == 120


# S4-81-02 - AC2: before opening, refused with the opening date.


@pytest.mark.django_db
def test_s4_81_02_ac2_before_opening_is_refused_with_the_opening_date(
    attendee_api_factory, attendee, confirmed_event
):
    opens = timezone.now() + datetime.timedelta(days=2)
    open_policy(confirmed_event, opens_at=opens)
    api = attendee_api_factory(attendee)

    response = api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "not_open"
    assert datetime.datetime.fromisoformat(str(response.data["opens_at"])) == opens
    local = timezone.localtime(opens)
    assert f"{local:%d %b %Y %H:%M}" in response.data["detail"]
    assert not Registration.objects.exists()


@pytest.mark.django_db
def test_s4_81_02_exactly_at_opening_is_allowed(confirmed_event):
    policy = open_policy(confirmed_event, opens_at=NOW)

    assert window_problem(policy, NOW) is None
    assert window_problem(policy, NOW - datetime.timedelta(seconds=1)).code == "not_open"


# S4-81-03 - AC3: after closing (or manual closure), refused.


@pytest.mark.django_db
def test_s4_81_03_ac3_after_closing_is_refused(api, attendee, confirmed_event):
    open_policy(
        confirmed_event,
        opens_at=timezone.now() - datetime.timedelta(days=5),
        closes_at=timezone.now() - datetime.timedelta(minutes=1),
    )
    api.force_authenticate(attendee)

    response = api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "closed"
    assert not Registration.objects.exists()


@pytest.mark.django_db
def test_s4_81_03_exactly_at_closing_is_refused(confirmed_event):
    policy = open_policy(confirmed_event, opens_at=NOW - datetime.timedelta(days=1), closes_at=NOW)

    assert window_problem(policy, NOW).code == "closed"
    assert window_problem(policy, NOW - datetime.timedelta(seconds=1)) is None


@pytest.mark.django_db
def test_s4_81_03_manual_closure_refuses(attendee, confirmed_event):
    open_policy(confirmed_event, manually_closed=True)

    with pytest.raises(RegistrationRefused) as caught:
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert caught.value.code == "closed"


# S4-81-04 - AC4: two attempts for the last place: exactly one succeeds.


@pytest.mark.django_db(transaction=True)
def test_s4_81_04_ac4_two_attempts_for_the_last_place(
    attendee, second_attendee, third_attendee, confirmed_event
):
    if connection.vendor != "postgresql":
        pytest.skip("Row locks require PostgreSQL")
    open_policy(confirmed_event, capacity=2)
    register(event=confirmed_event, attendee=third_attendee, **details(third_attendee))
    barrier = Barrier(2)

    def attempt(user):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                register(event=confirmed_event, attendee=user, **details(user))
                return "registered"
            except RegistrationRefused as exc:
                return exc.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(attempt, [attendee, second_attendee]))

    assert results == ["full", "registered"]
    assert Registration.objects.filter(status=RegistrationStatus.REGISTERED).count() == 2
    assert full_notices().filter(recipient=confirmed_event.created_by).count() == 1


# S4-81-05 - AC5: taking the final place notifies organiser and coordinator once.


@pytest.mark.django_db
def test_s4_81_05_ac5_the_final_place_notifies_organiser_and_coordinator(
    attendee, second_attendee, confirmed_event, organiser, coordinator
):
    open_policy(confirmed_event, capacity=2)
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))
    assert not full_notices().exists()

    register(event=confirmed_event, attendee=attendee, **details(attendee))

    assert set(full_notices().values_list("recipient_id", flat=True)) == {
        organiser.pk,
        coordinator.pk,
    }
    assert "all 2 places are taken" in full_notices().first().message


@pytest.mark.django_db
def test_s4_81_05_a_refused_attempt_on_a_full_event_sends_no_new_notice(
    attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event, capacity=1)
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))
    before = full_notices().count()

    with pytest.raises(RegistrationRefused):
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert full_notices().count() == before


# S4-81-06 - the organiser's policy controls.


@pytest.mark.django_db
def test_s4_81_06_the_organiser_sets_the_policy_with_history(
    signed_in_organiser, organiser, confirmed_event
):
    opens = (timezone.now() + datetime.timedelta(days=1)).replace(microsecond=0)
    closes = opens + datetime.timedelta(days=10)

    response = signed_in_organiser.put(
        policy_url(confirmed_event),
        {
            "enabled": True,
            "opens_at": opens.isoformat(),
            "closes_at": closes.isoformat(),
            "capacity": 80,
        },
        format="json",
    )

    assert response.status_code == 200
    assert (response.data["capacity"], response.data["registered"], response.data["open"]) == (
        80,
        0,
        False,
    )
    policy = RegistrationPolicy.objects.get(event=confirmed_event)
    assert (policy.opens_at, policy.closes_at, policy.updated_by) == (opens, closes, organiser)
    # An extension keeps its history.
    signed_in_organiser.put(
        policy_url(confirmed_event),
        {"closes_at": (closes + datetime.timedelta(days=5)).isoformat()},
        format="json",
    )
    changes = list(RegistrationPolicyChange.objects.filter(policy=policy).order_by("pk"))
    assert len(changes) == 2
    assert changes[1].before["closes_at"] == closes.isoformat()
    assert changes[1].after["capacity"] == 80


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body,field",
    [
        ({"enabled": True, "capacity": 0}, "capacity"),
        ({"enabled": True}, "capacity"),
        (
            {
                "enabled": True,
                "capacity": 5,
                "opens_at": "2027-01-02T10:00:00+08:00",
                "closes_at": "2027-01-02T10:00:00+08:00",
            },
            "closes_at",
        ),
    ],
)
def test_s4_81_06_invalid_policies_are_refused(signed_in_organiser, confirmed_event, body, field):
    response = signed_in_organiser.put(policy_url(confirmed_event), body, format="json")

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_s4_81_06_the_cap_cannot_drop_below_current_registrations(
    signed_in_organiser, attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event, capacity=5)
    for user in (attendee, second_attendee):
        register(event=confirmed_event, attendee=user, **details(user))

    response = signed_in_organiser.put(policy_url(confirmed_event), {"capacity": 1}, format="json")

    assert response.status_code == 400
    assert "2 people are already registered" in response.data["capacity"][0]
    assert RegistrationPolicy.objects.get(event=confirmed_event).capacity == 5
    assert Registration.objects.filter(status=RegistrationStatus.REGISTERED).count() == 2


@pytest.mark.django_db
def test_s4_81_06_raising_the_cap_reopens_a_full_event(
    signed_in_organiser, attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event, capacity=1)
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))

    signed_in_organiser.put(policy_url(confirmed_event), {"capacity": 2}, format="json")

    assert register(event=confirmed_event, attendee=attendee, **details(attendee)).pk


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["other_organiser", "coordinator", "lead", "attendee"])
def test_s4_81_06_only_the_events_organiser_changes_the_policy(api, confirmed_event, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    response = api.put(policy_url(confirmed_event), {"enabled": True, "capacity": 5}, format="json")

    assert response.status_code == 403
    assert not RegistrationPolicy.objects.filter(event=confirmed_event).exists()
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s4_81_06_managers_see_the_registrations_but_others_do_not(
    api, attendee, confirmed_event, coordinator, other_organiser, second_coordinator
):
    open_policy(confirmed_event)
    register(event=confirmed_event, attendee=attendee, **details(attendee))

    api.force_authenticate(coordinator)
    data = api.get(f"/api/events/{confirmed_event.pk}/registrations/").data
    assert data["registered"] == 1
    assert [r["full_name"] for r in data["registrations"]] == ["Andy Attendee"]
    for outsider in (other_organiser, second_coordinator):
        api.force_authenticate(outsider)
        assert api.get(f"/api/events/{confirmed_event.pk}/registrations/").status_code == 403


@pytest.fixture
def attendee_api_factory(api):
    def make(user):
        api.force_authenticate(user)
        return api

    return make


@pytest.mark.django_db
@pytest.mark.parametrize(
    "values,field",
    [
        ({"enabled": "yes", "capacity": 5}, "enabled"),
        ({"manually_closed": None, "capacity": 5}, "manually_closed"),
        ({"opens_at": datetime.datetime(2027, 1, 1, 9), "capacity": 5}, "opens_at"),
        ({"capacity": True}, "capacity"),
    ],
)
def test_s4_81_06_the_service_validates_each_field(organiser, confirmed_event, values, field):
    from apps.registrations.services import PolicyInvalid, set_policy

    with pytest.raises(PolicyInvalid) as caught:
        set_policy(event=confirmed_event, actor=organiser, **values)
    assert field in caught.value.errors


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.DRAFT, EventStatus.CANCELLED])
def test_s4_81_06_a_draft_or_cancelled_event_has_no_registration_settings(
    organiser, confirmed_event, status
):
    from apps.registrations.services import PolicyInvalid, set_policy

    confirmed_event.status = status
    confirmed_event.save(update_fields=["status"])

    with pytest.raises(PolicyInvalid) as caught:
        set_policy(event=confirmed_event, actor=organiser, enabled=True, capacity=5)
    assert "event" in caught.value.errors


@pytest.mark.django_db
def test_s4_81_06_managers_read_the_policy_and_outsiders_cannot(
    api, confirmed_event, lead, coordinator, second_coordinator
):
    open_policy(confirmed_event, capacity=10)

    for manager in (lead, coordinator):
        api.force_authenticate(manager)
        data = api.get(policy_url(confirmed_event)).data
        assert (data["capacity"], data["remaining"], data["open"]) == (10, 10, True)
    api.force_authenticate(second_coordinator)
    assert api.get(policy_url(confirmed_event)).status_code == 403


@pytest.mark.django_db
def test_s4_81_06_a_disabled_policy_needs_no_capacity_yet(organiser, attendee, confirmed_event):
    from apps.registrations.models import RegistrationHistory
    from apps.registrations.services import set_policy

    policy = set_policy(event=confirmed_event, actor=organiser, enabled=False)

    assert (policy.enabled, policy.capacity) == (False, None)
    assert capacity_of(confirmed_event).capacity is None
    # Every record names itself in the admin.
    set_policy(event=confirmed_event, actor=organiser, enabled=True, capacity=3)
    registration = register(event=confirmed_event, attendee=attendee, **details(attendee))
    for record in (
        policy,
        policy.changes.first(),
        registration,
        RegistrationHistory.objects.get(registration=registration),
    ):
        assert str(record)
