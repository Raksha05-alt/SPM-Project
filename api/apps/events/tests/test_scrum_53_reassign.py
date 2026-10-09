"""SCRUM-53 (US-05.2) - reassign an event to a different coordinator."""

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import CoordinatorAssignment
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event


def reassign(api, event, coordinator):
    return api.post(
        f"/api/events/{event.pk}/reassign/", {"coordinator": coordinator.pk}, format="json"
    )


@pytest.fixture
def second_coordinator(db):
    return User.objects.create_user(
        username="second@connectsphere.example",
        email="second@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
        first_name="Sam",
        last_name="Second",
    )


@pytest.fixture
def assigned_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)


@pytest.mark.django_db
def test_ac1_the_new_coordinator_becomes_responsible_and_everyone_is_notified(
    signed_in_coordinator, organiser, coordinator, second_coordinator, assigned_event
):
    response = reassign(signed_in_coordinator, assigned_event, second_coordinator)

    assert response.status_code == 200
    assert response.data["coordinator"] == second_coordinator.pk
    assert response.data["coordinator_name"] == "Sam Second"
    recipients = set(
        Notification.objects.filter(
            event=assigned_event, kind=NotificationKind.REASSIGNED
        ).values_list("recipient", flat=True)
    )
    assert recipients == {organiser.pk, coordinator.pk, second_coordinator.pk}


@pytest.mark.django_db
def test_ac1_an_unassigned_flagged_event_can_be_given_a_coordinator(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, assignment_requires_attention=True)

    response = reassign(signed_in_coordinator, event, coordinator)

    assert response.status_code == 200
    event.refresh_from_db()
    assert event.coordinator == coordinator
    assert event.assignment_requires_attention is False
    assert CoordinatorAssignment.objects.get(event=event).previous_coordinator is None


@pytest.mark.django_db
def test_ac2_the_previous_assignment_is_kept_with_who_changed_it_and_when(
    signed_in_coordinator, coordinator, second_coordinator, assigned_event
):
    reassign(signed_in_coordinator, assigned_event, second_coordinator)

    entry = CoordinatorAssignment.objects.get(event=assigned_event)
    assert entry.previous_coordinator == coordinator
    assert entry.coordinator == second_coordinator
    assert entry.changed_by == coordinator
    assert entry.changed_at is not None
    detail = signed_in_coordinator.get(f"/api/events/{assigned_event.pk}/")
    assert detail.data["assignment_history"][0]["previous_coordinator_name"] == "Cora Coordinator"
    assert detail.data["assignment_history"][0]["changed_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
def test_ac2_the_automatic_assignment_on_submission_is_also_recorded(
    signed_in_organiser, coordinator, complete_draft
):
    signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")

    entry = CoordinatorAssignment.objects.get(event=complete_draft)
    assert entry.coordinator == coordinator
    assert entry.changed_by is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_ac3_a_closed_event_cannot_be_reassigned(
    signed_in_coordinator, organiser, coordinator, second_coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = reassign(signed_in_coordinator, event, second_coordinator)

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.coordinator == coordinator
    assert AuditLog.objects.filter(actor=coordinator, allowed=False).exists()


@pytest.mark.django_db
def test_ac4_the_previous_coordinator_loses_coordinator_actions(
    api, coordinator, second_coordinator, organiser
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)
    reassign(api, event, second_coordinator)

    response = api.post(f"/api/events/{event.pk}/approve/")

    assert response.status_code == 403
    event.refresh_from_db()
    assert event.status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_reassigning_to_the_current_coordinator_is_refused(
    signed_in_coordinator, coordinator, assigned_event
):
    response = reassign(signed_in_coordinator, assigned_event, coordinator)

    assert response.status_code == 400


@pytest.mark.django_db
def test_reassigning_to_someone_who_is_not_a_coordinator_is_refused(
    signed_in_coordinator, venue_staff, assigned_event
):
    response = reassign(signed_in_coordinator, assigned_event, venue_staff)

    assert response.status_code == 400
    assert "coordinator" in response.data


@pytest.mark.django_db
def test_an_organiser_cannot_reassign_their_event(
    signed_in_organiser, second_coordinator, assigned_event
):
    response = reassign(signed_in_organiser, assigned_event, second_coordinator)

    assert response.status_code == 403


@pytest.mark.django_db
def test_the_coordinator_list_shows_active_coordinators_to_staff_only(
    api, coordinator, second_coordinator, organiser
):
    api.force_authenticate(coordinator)
    staff_view = api.get("/api/coordinators/")
    api.force_authenticate(organiser)
    client_view = api.get("/api/coordinators/")

    assert staff_view.status_code == 200
    assert {row["email"] for row in staff_view.data} == {
        coordinator.email,
        second_coordinator.email,
    }
    assert client_view.status_code == 403


@pytest.mark.django_db
def test_assignment_history_is_hidden_from_the_client(
    signed_in_coordinator, api, organiser, second_coordinator, assigned_event
):
    reassign(signed_in_coordinator, assigned_event, second_coordinator)
    api.force_authenticate(organiser)

    response = api.get(f"/api/events/{assigned_event.pk}/")

    assert "assignment_history" not in response.data
