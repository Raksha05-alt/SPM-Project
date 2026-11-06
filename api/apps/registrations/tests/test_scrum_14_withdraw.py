"""SCRUM-14 - Withdraw from an event registration.

As an Attendee, I want to withdraw my registration for an event I can no longer
attend, so that I stop receiving information about it and my place becomes
available to someone else.

Case IDs follow the Sprint 4 guide: S4-14-<case>.
"""

import datetime

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import Registration, RegistrationHistory, RegistrationStatus
from apps.registrations.services import (
    NotRegistrationOwner,
    RegistrationRefused,
    capacity_of,
    register,
    withdraw,
    withdrawal_summary,
)
from apps.registrations.tests.conftest import details, open_policy


def withdraw_url(registration):
    return f"/api/registrations/{registration.pk}/withdraw/"


def register_url(event):
    return f"/api/events/{event.pk}/registration/"


@pytest.fixture
def registered(attendee, confirmed_event):
    open_policy(confirmed_event, capacity=2)
    return register(event=confirmed_event, attendee=attendee, **details(attendee))


@pytest.fixture
def attendee_api(api, attendee):
    api.force_authenticate(attendee)
    return api


# S4-14-01 - AC1: a summary first; confirming withdraws and confirms.


@pytest.mark.django_db
def test_s4_14_01_ac1_the_summary_comes_first_and_changes_nothing(attendee_api, registered):
    summary = attendee_api.get(withdraw_url(registered)).data

    assert summary["event_name"] == "Harbour Gala"
    assert (summary["can_withdraw"], summary["releases_place"]) == (True, True)
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED


@pytest.mark.django_db
def test_s4_14_01_ac1_without_confirmation_nothing_is_withdrawn(attendee_api, registered):
    response = attendee_api.post(withdraw_url(registered), {}, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "confirm_required"
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED
    assert registered.history.count() == 1


@pytest.mark.django_db
def test_s4_14_01_ac1_confirming_withdraws_and_confirms(attendee_api, attendee, registered):
    response = attendee_api.post(withdraw_url(registered), {"confirm": True}, format="json")

    assert response.status_code == 200
    assert response.data["registration"]["status"] == RegistrationStatus.WITHDRAWN
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.WITHDRAWN
    assert registered.withdrawn_at is not None
    last = registered.history.order_by("-pk").first()
    assert (last.from_status, last.to_status, last.actor) == (
        RegistrationStatus.REGISTERED,
        RegistrationStatus.WITHDRAWN,
        attendee,
    )
    notice = Notification.objects.get(kind=NotificationKind.REG_WITHDRAWN)
    assert notice.recipient == attendee
    assert "withdrawn your registration" in notice.message


# S4-14-02 - AC2: the count drops by exactly one and the place is free again.


@pytest.mark.django_db
def test_s4_14_02_ac2_the_count_drops_and_the_place_is_free(
    attendee, second_attendee, third_attendee, confirmed_event, registered
):
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))
    assert capacity_of(confirmed_event).full is True
    with pytest.raises(RegistrationRefused):
        register(event=confirmed_event, attendee=third_attendee, **details(third_attendee))

    withdraw(registration=registered, actor=attendee, confirm=True)

    assert capacity_of(confirmed_event).registered == 1
    assert register(event=confirmed_event, attendee=third_attendee, **details(third_attendee)).pk


@pytest.mark.django_db
def test_s4_14_02_withdrawing_twice_does_not_release_twice(attendee, confirmed_event, registered):
    withdraw(registration=registered, actor=attendee, confirm=True)

    with pytest.raises(RegistrationRefused) as caught:
        withdraw(registration=registered, actor=attendee, confirm=True)
    assert caught.value.code == "already_withdrawn"
    assert RegistrationHistory.objects.filter(registration=registered).count() == 2
    assert Notification.objects.filter(kind=NotificationKind.REG_WITHDRAWN).count() == 1


# S4-14-03 - AC3: a withdrawn attendee may register again while open and below capacity.


@pytest.mark.django_db
def test_s4_14_03_ac3_registering_again_after_withdrawing(
    attendee_api, attendee, confirmed_event, registered
):
    withdraw(registration=registered, actor=attendee, confirm=True)

    response = attendee_api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 201
    rows = Registration.objects.filter(attendee=attendee).order_by("pk")
    assert [r.status for r in rows] == [RegistrationStatus.WITHDRAWN, RegistrationStatus.REGISTERED]


@pytest.mark.django_db
def test_s4_14_03_registering_again_still_needs_open_registration(
    attendee, confirmed_event, registered
):
    withdraw(registration=registered, actor=attendee, confirm=True)
    registered.event.registration_policy.manually_closed = True
    registered.event.registration_policy.save(update_fields=["manually_closed"])

    with pytest.raises(RegistrationRefused) as caught:
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert caught.value.code == "closed"


# S4-14-04 - AC4: an event that has taken place refuses, with the reason.


@pytest.mark.django_db
def test_s4_14_04_ac4_after_the_event_withdrawal_is_refused(
    attendee_api, confirmed_event, registered
):
    past = timezone.now() - datetime.timedelta(days=1)
    confirmed_event.preferred_start = past - datetime.timedelta(hours=6)
    confirmed_event.preferred_end = past
    confirmed_event.save(update_fields=["preferred_start", "preferred_end"])

    summary = attendee_api.get(withdraw_url(registered)).data
    response = attendee_api.post(withdraw_url(registered), {"confirm": True}, format="json")

    assert summary["can_withdraw"] is False
    assert response.status_code == 409
    assert response.data["code"] == "event_over"
    assert response.data["detail"] == "This event has already taken place, so you cannot withdraw."
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status,code",
    [(EventStatus.COMPLETED, "event_over"), (EventStatus.CANCELLED, "not_withdrawable")],
)
def test_s4_14_04_completed_or_cancelled_events_refuse(
    attendee, confirmed_event, registered, status, code
):
    confirmed_event.status = status
    confirmed_event.save(update_fields=["status"])

    with pytest.raises(RegistrationRefused) as caught:
        withdraw(registration=registered, actor=attendee, confirm=True)
    assert caught.value.code == code


@pytest.mark.django_db
def test_s4_14_04_a_future_event_back_in_planning_can_still_be_withdrawn(
    attendee, confirmed_event, registered
):
    confirmed_event.status = EventStatus.PLANNING
    confirmed_event.save(update_fields=["status"])

    assert withdraw(registration=registered, actor=attendee, confirm=True).status == (
        RegistrationStatus.WITHDRAWN
    )


# S4-14-05 - AC5: organiser and coordinator see it as withdrawn, not removed.


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["organiser", "coordinator"])
def test_s4_14_05_ac5_managers_see_the_withdrawn_registration(
    api, attendee, confirmed_event, registered, request, who
):
    withdraw(registration=registered, actor=attendee, confirm=True)
    api.force_authenticate(request.getfixturevalue(who))

    data = api.get(f"/api/events/{confirmed_event.pk}/registrations/").data

    assert data["registered"] == 0
    assert [(r["full_name"], r["status"]) for r in data["registrations"]] == [
        ("Andy Attendee", RegistrationStatus.WITHDRAWN)
    ]
    assert data["registrations"][0]["withdrawn_at"] is not None


# S4-14-06 - AC6: only the attendee who registered may withdraw.


@pytest.mark.django_db
def test_s4_14_06_ac6_another_attendee_cannot_withdraw(api, second_attendee, registered):
    api.force_authenticate(second_attendee)

    assert api.get(withdraw_url(registered)).status_code == 403
    assert api.post(withdraw_url(registered), {"confirm": True}, format="json").status_code == 403
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED
    assert AuditLog.objects.filter(actor=second_attendee, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["organiser", "coordinator", "lead"])
def test_s4_14_06_staff_cannot_withdraw_an_attendee(api, registered, request, who):
    api.force_authenticate(request.getfixturevalue(who))

    assert api.post(withdraw_url(registered), {"confirm": True}, format="json").status_code == 403
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED


@pytest.mark.django_db
def test_s4_14_06_the_service_also_checks_the_owner(second_attendee, registered):
    with pytest.raises(NotRegistrationOwner):
        withdraw(registration=registered, actor=second_attendee, confirm=True)
    with pytest.raises(NotRegistrationOwner):
        withdrawal_summary(registered, second_attendee)


@pytest.mark.django_db
def test_s4_14_06_a_failed_notice_leaves_no_partial_withdrawal(attendee, registered):
    from unittest import mock

    with (
        mock.patch("apps.registrations.services.notify", side_effect=RuntimeError("notices down")),
        pytest.raises(RuntimeError),
    ):
        withdraw(registration=registered, actor=attendee, confirm=True)
    registered.refresh_from_db()
    assert registered.status == RegistrationStatus.REGISTERED
    assert registered.history.count() == 1
