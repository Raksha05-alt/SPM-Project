"""Approve a submitted event request."""

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event


def approve_url(event):
    return f"/api/events/{event.pk}/approve/"


@pytest.fixture
def other_coordinator(db):
    return User.objects.create_user(
        username="second@connectsphere.example",
        email="second@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
    )


@pytest.fixture
def my_submitted_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)


@pytest.mark.django_db
def test_ac1_approving_moves_the_request_to_approved_and_notifies_the_organiser(
    signed_in_coordinator, coordinator, organiser, my_submitted_event
):
    response = signed_in_coordinator.post(approve_url(my_submitted_event))

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.APPROVED
    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.APPROVED
    assert EventStatusHistory.objects.filter(
        event=my_submitted_event, to_status=EventStatus.APPROVED, changed_by=coordinator
    ).exists()
    notice = Notification.objects.get(
        recipient=organiser, event=my_submitted_event, kind=NotificationKind.APPROVED
    )
    assert "approved" in notice.message


@pytest.mark.django_db
def test_ac1_the_organiser_is_notified_even_after_an_assignment_notice(
    signed_in_coordinator, organiser, my_submitted_event
):
    Notification.objects.create(
        recipient=organiser, event=my_submitted_event, message="You have a coordinator."
    )

    response = signed_in_coordinator.post(approve_url(my_submitted_event))

    assert response.status_code == 200
    assert Notification.objects.filter(recipient=organiser, event=my_submitted_event).count() == 2


@pytest.mark.django_db
def test_ac1_a_request_awaiting_clarification_can_also_be_approved(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)

    assert signed_in_coordinator.post(approve_url(event)).status_code == 200


@pytest.mark.django_db
def test_ac1_a_request_without_sufficient_information_is_not_approved(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(
        organiser, status=EventStatus.SUBMITTED, coordinator=coordinator, expected_attendance=None
    )

    response = signed_in_coordinator.post(approve_url(event))

    assert response.status_code == 400
    assert response.data["missing_fields"] == ["expected_attendance"]
    event.refresh_from_db()
    assert event.status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_ac2_the_approving_coordinator_and_timestamp_are_recorded_and_visible_internally(
    signed_in_coordinator, coordinator, my_submitted_event
):
    signed_in_coordinator.post(approve_url(my_submitted_event))

    my_submitted_event.refresh_from_db()
    assert my_submitted_event.approved_by == coordinator
    assert my_submitted_event.approved_at == my_submitted_event.status_changed_at

    detail = signed_in_coordinator.get(f"/api/events/{my_submitted_event.pk}/")
    assert detail.data["approved_by_name"] == "Cora Coordinator"
    assert detail.data["approved_at"]

    queue_row = signed_in_coordinator.get("/api/events/queue/").data[0]
    assert queue_row["approved_by_name"] == "Cora Coordinator"
    assert queue_row["approved_at"]


@pytest.mark.django_db
def test_ac2_the_approval_decision_is_not_shown_to_the_client(
    signed_in_coordinator, api, organiser, my_submitted_event
):
    signed_in_coordinator.post(approve_url(my_submitted_event))

    api.force_authenticate(organiser)
    detail = api.get(f"/api/events/{my_submitted_event.pk}/")

    assert detail.status_code == 200
    assert "approved_by_name" not in detail.data
    assert "approved_at" not in detail.data


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_ac3_a_request_not_in_a_reviewable_status_cannot_be_approved(
    signed_in_coordinator, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(approve_url(event))

    assert response.status_code == 409
    event.refresh_from_db()
    assert event.status == status
    assert event.approved_by is None
    assert AuditLog.objects.filter(action=f"POST /api/events/{event.pk}/approve/").exists()


@pytest.mark.django_db
def test_ac3_a_draft_cannot_be_approved(signed_in_coordinator, organiser, coordinator):
    draft = make_event(organiser, coordinator=coordinator)

    assert signed_in_coordinator.post(approve_url(draft)).status_code == 403


@pytest.mark.django_db
def test_ac4_a_coordinator_not_assigned_to_the_event_cannot_approve_it(
    api, other_coordinator, organiser, my_submitted_event
):
    api.force_authenticate(other_coordinator)

    response = api.post(approve_url(my_submitted_event))

    assert response.status_code == 403
    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED
    assert not Notification.objects.filter(kind=NotificationKind.APPROVED).exists()
    assert AuditLog.objects.filter(
        actor=other_coordinator, action=f"POST /api/events/{my_submitted_event.pk}/approve/"
    ).exists()


@pytest.mark.django_db
def test_ac4_an_unassigned_event_cannot_be_approved(signed_in_coordinator, submitted_event):
    assert signed_in_coordinator.post(approve_url(submitted_event)).status_code == 403


@pytest.mark.django_db
def test_ac4_an_organiser_or_attendee_cannot_approve(api, organiser, attendee, coordinator):
    confirmed = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    submitted = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)

    api.force_authenticate(organiser)
    assert api.post(approve_url(submitted)).status_code == 403

    api.force_authenticate(attendee)
    assert api.post(approve_url(confirmed)).status_code == 403

    submitted.refresh_from_db()
    assert submitted.status == EventStatus.SUBMITTED
