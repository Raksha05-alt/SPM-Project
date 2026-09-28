"""SCRUM-54 - See the events assigned to me."""

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from conftest import PASSWORD, make_event

MINE = "/api/events/mine/"


@pytest.fixture
def other_coordinator(db):
    return User.objects.create_user(
        username="second@connectsphere.example",
        email="second@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
    )


@pytest.mark.django_db
def test_ac1_the_list_shows_only_my_events_with_status_and_next_action(
    signed_in_coordinator, coordinator, organiser
):
    mine = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    make_event(organiser, status=EventStatus.SUBMITTED, name="Unassigned")

    response = signed_in_coordinator.get(MINE)

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [mine.pk]
    row = response.data[0]
    for field in ("status", "status_label", "status_description", "next_action"):
        assert row[field]
    assert row["requires_action"] is True


@pytest.mark.django_db
def test_ac2_events_requiring_action_appear_first(signed_in_coordinator, coordinator, organiser):
    now = timezone.now()
    waiting = make_event(
        organiser,
        status=EventStatus.UNDER_REVIEW,
        coordinator=coordinator,
        name="Waiting on client",
        submitted_at=now - timezone.timedelta(days=9),
    )
    planning = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Planning",
        submitted_at=now - timezone.timedelta(days=1),
    )
    newly_submitted = make_event(
        organiser,
        status=EventStatus.SUBMITTED,
        coordinator=coordinator,
        name="New",
        submitted_at=now - timezone.timedelta(days=3),
    )

    response = signed_in_coordinator.get(MINE)

    ids = [row["id"] for row in response.data]
    assert ids == [newly_submitted.pk, planning.pk, waiting.pk]
    assert [row["requires_action"] for row in response.data] == [True, True, False]


@pytest.mark.django_db
def test_ac3_no_assigned_events_shows_an_empty_list_rather_than_an_error(
    signed_in_coordinator,
):
    response = signed_in_coordinator.get(MINE)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_ac4_an_event_assigned_to_another_coordinator_does_not_appear(
    signed_in_coordinator, other_coordinator, organiser
):
    theirs = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=other_coordinator)

    response = signed_in_coordinator.get(MINE)

    assert theirs.pk not in [row["id"] for row in response.data]


@pytest.mark.django_db
def test_only_a_coordinator_can_open_the_list_and_refusals_are_audited(
    api, organiser, attendee
):
    for user in (organiser, attendee):
        api.force_authenticate(user)
        assert api.get(MINE).status_code == 403

    assert AuditLog.objects.filter(action="GET /api/events/mine/").count() == 2
