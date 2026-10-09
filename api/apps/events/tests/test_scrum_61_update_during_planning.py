"""SCRUM-61 (US-07.1) - update event information during planning."""

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventChangeLog
from conftest import PASSWORD, make_event


def edit(api, event, data):
    return api.patch(f"/api/events/{event.pk}/", data, format="json")


@pytest.fixture
def planning_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


@pytest.mark.django_db
def test_ac1_the_assigned_coordinator_saves_new_values_that_everyone_with_access_sees(
    api, signed_in_coordinator, organiser, planning_event
):
    response = edit(
        signed_in_coordinator,
        planning_event,
        {"description": "Keynote, two panels and a networking lunch.", "expected_attendance": 140},
    )

    assert response.status_code == 200
    api.force_authenticate(organiser)
    client_view = api.get(f"/api/events/{planning_event.pk}/")
    assert client_view.data["description"] == "Keynote, two panels and a networking lunch."
    assert client_view.data["expected_attendance"] == 140


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    ],
)
def test_ac1_the_coordinator_can_edit_in_every_open_planning_status(
    signed_in_coordinator, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = edit(signed_in_coordinator, event, {"purpose": "Updated purpose"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_ac2_a_coordinator_who_is_not_assigned_cannot_edit(api, planning_event):
    other = User.objects.create_user(
        username="other@connectsphere.example",
        email="other@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
    )
    api.force_authenticate(other)

    response = edit(api, planning_event, {"name": "Hijacked"})

    assert response.status_code == 403
    planning_event.refresh_from_db()
    assert planning_event.name == "Regional Partner Conference"
    assert AuditLog.objects.filter(actor=other, allowed=False).exists()


@pytest.mark.django_db
def test_ac2_the_client_cannot_edit_an_event_that_is_in_planning(
    signed_in_organiser, planning_event
):
    response = edit(signed_in_organiser, planning_event, {"name": "Client rename"})

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.COMPLETED, EventStatus.CANCELLED])
def test_ac3_a_completed_or_cancelled_event_cannot_be_edited(
    signed_in_coordinator, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = edit(signed_in_coordinator, event, {"description": "Too late"})

    assert response.status_code == 403
    event.refresh_from_db()
    assert event.description == ""


@pytest.mark.django_db
def test_ac4_the_editing_user_and_timestamp_are_recorded(
    signed_in_coordinator, coordinator, planning_event
):
    before = timezone.now()

    response = edit(signed_in_coordinator, planning_event, {"purpose": "Partner onboarding"})

    planning_event.refresh_from_db()
    assert planning_event.updated_by == coordinator
    assert planning_event.updated_at >= before
    assert response.data["updated_by_name"] == "Cora Coordinator"
    entry = EventChangeLog.objects.get(event=planning_event, field="purpose")
    assert entry.changed_by == coordinator
    assert entry.changed_at >= before


@pytest.mark.django_db
def test_validation_rules_still_apply_to_coordinator_edits(signed_in_coordinator, planning_event):
    response = edit(signed_in_coordinator, planning_event, {"expected_attendance": 0})

    assert response.status_code == 400
    assert "expected_attendance" in response.data


@pytest.mark.django_db
def test_a_coordinator_edit_cannot_change_the_status_directly(
    signed_in_coordinator, planning_event
):
    response = edit(signed_in_coordinator, planning_event, {"status": EventStatus.CONFIRMED})

    assert response.status_code == 200
    planning_event.refresh_from_db()
    assert planning_event.status == EventStatus.PLANNING
