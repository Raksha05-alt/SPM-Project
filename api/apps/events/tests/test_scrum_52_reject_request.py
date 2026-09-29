"""SCRUM-52 - Reject a submitted event request with a recorded reason."""

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus, InvalidTransition
from apps.events.models import EventStatusHistory
from apps.events.services import transition_event
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event

REASON = "We cannot host events of over 500 people on the requested date."


def reject_url(event):
    return f"/api/events/{event.pk}/reject/"


def detail_url(event):
    return f"/api/events/{event.pk}/"


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


@pytest.fixture
def rejected_event(signed_in_coordinator, my_submitted_event):
    response = signed_in_coordinator.post(
        reject_url(my_submitted_event), {"reason": REASON}, format="json"
    )
    assert response.status_code == 200
    my_submitted_event.refresh_from_db()
    return my_submitted_event


@pytest.mark.django_db
def test_ac1_rejecting_with_a_reason_sets_rejected_and_notifies_the_organiser(
    organiser, coordinator, rejected_event
):
    assert rejected_event.status == EventStatus.REJECTED
    assert rejected_event.rejection_reason == REASON
    assert rejected_event.rejected_by == coordinator
    assert rejected_event.rejected_at == rejected_event.status_changed_at
    assert EventStatusHistory.objects.filter(
        event=rejected_event, to_status=EventStatus.REJECTED, changed_by=coordinator
    ).exists()

    notice = Notification.objects.get(
        recipient=organiser, event=rejected_event, kind=NotificationKind.REJECTED
    )
    assert REASON in notice.message


@pytest.mark.django_db
def test_ac1_a_request_awaiting_clarification_can_also_be_rejected(
    signed_in_coordinator, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)

    response = signed_in_coordinator.post(reject_url(event), {"reason": REASON}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.REJECTED


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": "   "}])
def test_ac2_a_rejection_without_a_reason_is_blocked(
    signed_in_coordinator, my_submitted_event, payload
):
    response = signed_in_coordinator.post(reject_url(my_submitted_event), payload, format="json")

    assert response.status_code == 400
    assert "reason" in response.data
    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED
    assert my_submitted_event.rejection_reason == ""
    assert not Notification.objects.filter(kind=NotificationKind.REJECTED).exists()


@pytest.mark.django_db
def test_ac3_the_organiser_sees_the_decision_reason_and_date(api, organiser, rejected_event):
    api.force_authenticate(organiser)

    data = api.get(detail_url(rejected_event)).data

    assert data["status"] == EventStatus.REJECTED
    assert data["status_label"] == "Rejected"
    assert data["rejection_reason"] == REASON
    assert data["rejected_at"]
    # Who made the decision stays internal, as for approvals.
    assert "rejected_by_name" not in data


@pytest.mark.django_db
def test_ac3_internal_users_also_see_who_rejected_it(signed_in_coordinator, rejected_event):
    data = signed_in_coordinator.get(detail_url(rejected_event)).data

    assert data["rejected_by_name"] == "Cora Coordinator"
    assert data["rejection_reason"] == REASON


@pytest.mark.django_db
def test_ac3_the_organiser_cannot_edit_or_resubmit_a_rejected_request(
    api, organiser, rejected_event
):
    api.force_authenticate(organiser)

    assert api.get(detail_url(rejected_event)).data["is_editable"] is False
    assert (
        api.patch(detail_url(rejected_event), {"name": "Retry"}, format="json").status_code == 403
    )
    assert api.post(f"/api/events/{rejected_event.pk}/submit/").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "target",
    [EventStatus.PLANNING, EventStatus.APPROVED, EventStatus.CONFIRMED, EventStatus.SUBMITTED],
)
def test_ac4_a_rejected_request_cannot_be_progressed(rejected_event, coordinator, target):
    with pytest.raises(InvalidTransition):
        transition_event(rejected_event, target, coordinator)

    rejected_event.refresh_from_db()
    assert rejected_event.status == EventStatus.REJECTED


@pytest.mark.django_db
def test_ac4_approving_a_rejected_request_is_refused(signed_in_coordinator, rejected_event):
    response = signed_in_coordinator.post(f"/api/events/{rejected_event.pk}/approve/")

    assert response.status_code == 409
    rejected_event.refresh_from_db()
    assert rejected_event.status == EventStatus.REJECTED


@pytest.mark.django_db
def test_a_request_can_only_be_rejected_once(signed_in_coordinator, rejected_event):
    response = signed_in_coordinator.post(
        reject_url(rejected_event), {"reason": "Again"}, format="json"
    )

    assert response.status_code == 409
    rejected_event.refresh_from_db()
    assert rejected_event.rejection_reason == REASON
    assert AuditLog.objects.filter(action=f"POST /api/events/{rejected_event.pk}/reject/").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.COMPLETED]
)
def test_only_a_request_under_review_can_be_rejected(
    signed_in_coordinator, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(reject_url(event), {"reason": REASON}, format="json")

    assert response.status_code == 409


@pytest.mark.django_db
def test_only_the_assigned_coordinator_can_reject(
    api, other_coordinator, organiser, my_submitted_event
):
    for user in (other_coordinator, organiser):
        api.force_authenticate(user)
        response = api.post(reject_url(my_submitted_event), {"reason": REASON}, format="json")
        assert response.status_code == 403

    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED
    assert AuditLog.objects.filter(
        actor=other_coordinator, action=f"POST /api/events/{my_submitted_event.pk}/reject/"
    ).exists()
