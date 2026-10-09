"""SCRUM-56 (US-06.2) - status changes only through permitted transitions."""

import itertools

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import (
    ALLOWED_TRANSITIONS,
    EventStatus,
    InvalidTransition,
    validate_transition,
)
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event

TERMINAL = (EventStatus.COMPLETED, EventStatus.CANCELLED)


def url(event, action):
    return f"/api/events/{event.pk}/{action}/"


@pytest.fixture
def my_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)


@pytest.fixture
def other_coordinator(db):
    return User.objects.create_user(
        username="second@connectsphere.example",
        email="second@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
    )


# --- AC1: an action not permitted from the current status is refused --------------

FORBIDDEN_PAIRS = [
    (current, target)
    for current, target in itertools.product(EventStatus.values, EventStatus.values)
    if target not in ALLOWED_TRANSITIONS[current]
]


@pytest.mark.parametrize("current,target", FORBIDDEN_PAIRS)
def test_ac1_every_transition_outside_the_table_is_refused(current, target):
    with pytest.raises(InvalidTransition):
        validate_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [(c, t) for c, targets in ALLOWED_TRANSITIONS.items() for t in sorted(targets)],
)
def test_ac1_every_transition_in_the_table_is_allowed(current, target):
    validate_transition(current, target)


@pytest.mark.django_db
def test_ac1_completing_an_event_that_is_still_in_planning_is_refused_and_unchanged(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)

    response = signed_in_coordinator.post(url(event, "complete"))

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert not EventStatusHistory.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_ac1_approving_a_confirmed_event_is_refused_and_unchanged(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)

    response = signed_in_coordinator.post(url(event, "approve"))

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.status == EventStatus.CONFIRMED


# --- AC2: a permitted action changes status and records user and timestamp --------


@pytest.mark.django_db
def test_ac2_cancelling_records_the_user_and_timestamp(
    signed_in_coordinator, coordinator, my_event
):
    before = timezone.now()

    response = signed_in_coordinator.post(
        url(my_event, "cancel"), {"reason": "Client budget withdrawn"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.CANCELLED
    assert response.data["cancellation_reason"] == "Client budget withdrawn"
    history = EventStatusHistory.objects.get(event=my_event, to_status=EventStatus.CANCELLED)
    assert history.from_status == EventStatus.SUBMITTED
    assert history.changed_by == coordinator
    assert history.changed_at >= before
    my_event.refresh_from_db()
    assert my_event.status_changed_at >= before


@pytest.mark.django_db
def test_ac2_completing_a_confirmed_event_after_it_ran_is_recorded(
    signed_in_coordinator, organiser, coordinator
):
    start = timezone.now() - timezone.timedelta(days=2)
    event = make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        coordinator=coordinator,
        preferred_start=start,
        preferred_end=start + timezone.timedelta(hours=4),
    )

    response = signed_in_coordinator.post(url(event, "complete"))

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.COMPLETED
    assert EventStatusHistory.objects.filter(
        event=event, to_status=EventStatus.COMPLETED, changed_by=coordinator
    ).exists()


@pytest.mark.django_db
def test_ac2_an_organiser_can_cancel_their_own_submitted_request(
    signed_in_organiser, organiser, my_event
):
    response = signed_in_organiser.post(url(my_event, "cancel"), {}, format="json")

    assert response.status_code == 200
    assert EventStatusHistory.objects.filter(
        event=my_event, to_status=EventStatus.CANCELLED, changed_by=organiser
    ).exists()


# --- AC3: a cancelled or completed event refuses every planning action ----------


@pytest.mark.django_db
@pytest.mark.parametrize("status", TERMINAL)
@pytest.mark.parametrize(
    "action,body",
    [
        ("approve", {}),
        ("reject", {"reason": "No longer possible"}),
        ("request-clarification", {"message": "More detail please"}),
        ("cancel", {}),
        ("complete", {}),
    ],
)
def test_ac3_planning_actions_on_a_terminal_event_are_refused(
    signed_in_coordinator, organiser, coordinator, status, action, body
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(url(event, action), body, format="json")

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.status == status


@pytest.mark.django_db
def test_ac3_a_rejected_event_cannot_be_cancelled(signed_in_coordinator, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.REJECTED, coordinator=coordinator)

    response = signed_in_coordinator.post(url(event, "cancel"))

    assert response.status_code == 409


# --- AC4: the users affected by a status change are notified -------------------


@pytest.mark.django_db
def test_ac4_a_coordinator_cancellation_notifies_the_organiser_only(
    signed_in_coordinator, organiser, coordinator, my_event
):
    signed_in_coordinator.post(url(my_event, "cancel"), {"reason": "Venue lost"}, format="json")

    notices = Notification.objects.filter(event=my_event, kind=NotificationKind.STATUS_CHANGED)
    assert [n.recipient for n in notices] == [organiser]
    assert "Cancelled" in notices[0].message
    assert "Venue lost" in notices[0].message


@pytest.mark.django_db
def test_ac4_an_organiser_cancellation_notifies_the_assigned_coordinator(
    signed_in_organiser, coordinator, my_event
):
    signed_in_organiser.post(url(my_event, "cancel"))

    notices = Notification.objects.filter(event=my_event, kind=NotificationKind.STATUS_CHANGED)
    assert [n.recipient for n in notices] == [coordinator]


@pytest.mark.django_db
def test_ac4_completion_notifies_the_organiser(signed_in_coordinator, organiser, coordinator):
    start = timezone.now() - timezone.timedelta(days=1)
    event = make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        coordinator=coordinator,
        preferred_start=start,
        preferred_end=start + timezone.timedelta(hours=2),
    )

    signed_in_coordinator.post(url(event, "complete"))

    assert Notification.objects.filter(
        event=event, recipient=organiser, kind=NotificationKind.STATUS_CHANGED
    ).exists()


@pytest.mark.django_db
def test_ac4_cancelling_an_unassigned_draft_notifies_nobody(signed_in_organiser, complete_draft):
    response = signed_in_organiser.post(url(complete_draft, "cancel"))

    assert response.status_code == 200
    assert not Notification.objects.filter(event=complete_draft).exists()


# --- permission edges ----------------------------------------------------------


@pytest.mark.django_db
def test_a_coordinator_who_is_not_assigned_cannot_cancel(api, other_coordinator, my_event):
    api.force_authenticate(other_coordinator)

    response = api.post(url(my_event, "cancel"))

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=other_coordinator, allowed=False).exists()
    my_event.refresh_from_db()
    assert my_event.status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_a_coordinator_who_is_not_assigned_cannot_complete(api, other_coordinator, organiser):
    event = make_event(organiser, status=EventStatus.CONFIRMED)
    api.force_authenticate(other_coordinator)

    response = api.post(url(event, "complete"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_an_organiser_cannot_complete_an_event(signed_in_organiser, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)

    response = signed_in_organiser.post(url(event, "complete"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_an_organiser_from_another_client_cannot_cancel(api, other_organiser, my_event):
    api.force_authenticate(other_organiser)

    response = api.post(url(my_event, "cancel"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_an_attendee_cannot_cancel_a_confirmed_event(api, attendee, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    api.force_authenticate(attendee)

    response = api.post(url(event, "cancel"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_an_event_cannot_be_completed_before_it_has_taken_place(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)

    response = signed_in_coordinator.post(url(event, "complete"))

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.status == EventStatus.CONFIRMED


@pytest.mark.django_db
def test_the_cancel_service_refuses_roles_with_no_relationship_to_the_event(venue_staff, my_event):
    from apps.events.services import NotPermitted, cancel_event

    with pytest.raises(NotPermitted):
        cancel_event(my_event, venue_staff)
