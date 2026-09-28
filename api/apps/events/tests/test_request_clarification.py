"""SCRUM-49 - Request clarification or amendment from the Event Organiser."""

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import ClarificationRequest, EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event


def clarify_url(event):
    return f"/api/events/{event.pk}/request-clarification/"


def submit_url(event):
    return f"/api/events/{event.pk}/submit/"


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
def awaiting_clarification(signed_in_coordinator, my_submitted_event):
    response = signed_in_coordinator.post(
        clarify_url(my_submitted_event),
        {
            "message": "How many attendees need wheelchair access?",
            "fields": ["accessibility_needs"],
        },
        format="json",
    )
    assert response.status_code == 200
    my_submitted_event.refresh_from_db()
    return my_submitted_event


@pytest.mark.django_db
def test_ac1_requesting_clarification_marks_it_awaited_and_notifies_the_organiser(
    organiser, coordinator, awaiting_clarification
):
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW
    assert awaiting_clarification.get_status_display() == "Awaiting Clarification"

    clarification = ClarificationRequest.objects.get(event=awaiting_clarification)
    assert clarification.message == "How many attendees need wheelchair access?"
    assert clarification.fields == ["accessibility_needs"]
    assert clarification.requested_by == coordinator
    assert clarification.resolved_at is None

    notice = Notification.objects.get(
        recipient=organiser, event=awaiting_clarification, kind=NotificationKind.CLARIFICATION
    )
    assert "wheelchair access" in notice.message


@pytest.mark.django_db
def test_ac1_the_organiser_sees_what_is_needed(api, organiser, awaiting_clarification):
    api.force_authenticate(organiser)

    data = api.get(detail_url(awaiting_clarification)).data

    assert data["status_label"] == "Awaiting Clarification"
    assert data["clarifications"][0]["message"] == "How many attendees need wheelchair access?"
    assert data["clarifications"][0]["fields"] == ["accessibility_needs"]
    assert data["clarifications"][0]["requested_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
def test_ac2_the_organiser_can_edit_the_request_and_resubmit(
    api, organiser, awaiting_clarification
):
    api.force_authenticate(organiser)
    assert api.get(detail_url(awaiting_clarification)).data["is_editable"] is True

    edited = api.patch(
        detail_url(awaiting_clarification),
        {"accessibility_needs": "Six wheelchair users; step-free access needed."},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.data["accessibility_needs"] == "Six wheelchair users; step-free access needed."

    resubmitted = api.post(submit_url(awaiting_clarification))
    assert resubmitted.status_code == 200
    assert resubmitted.data["status"] == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_ac2_the_organiser_still_cannot_delete_a_request_awaiting_clarification(
    api, organiser, awaiting_clarification
):
    api.force_authenticate(organiser)

    assert api.delete(detail_url(awaiting_clarification)).status_code == 403


@pytest.mark.django_db
def test_ac2_a_resubmission_still_needs_the_mandatory_fields(
    api, organiser, awaiting_clarification
):
    api.force_authenticate(organiser)
    api.patch(detail_url(awaiting_clarification), {"purpose": ""}, format="json")

    response = api.post(submit_url(awaiting_clarification))

    assert response.status_code == 400
    assert response.data["missing_fields"] == ["purpose"]
    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW


@pytest.mark.django_db
def test_ac3_a_resubmitted_request_returns_to_the_queue_with_its_history(
    api, signed_in_coordinator, organiser, coordinator, awaiting_clarification
):
    original_submitted_at = awaiting_clarification.submitted_at
    api.force_authenticate(organiser)
    api.post(submit_url(awaiting_clarification))

    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.status == EventStatus.SUBMITTED
    assert awaiting_clarification.coordinator == coordinator
    assert awaiting_clarification.submitted_at == original_submitted_at

    clarification = ClarificationRequest.objects.get(event=awaiting_clarification)
    assert clarification.resolved_at is not None
    assert list(
        EventStatusHistory.objects.filter(event=awaiting_clarification)
        .order_by("changed_at", "pk")
        .values_list("to_status", flat=True)
    ) == [EventStatus.UNDER_REVIEW, EventStatus.SUBMITTED]
    assert Notification.objects.filter(
        recipient=coordinator, event=awaiting_clarification, kind=NotificationKind.RESUBMITTED
    ).exists()

    api.force_authenticate(coordinator)
    queue = api.get("/api/events/queue/").data
    row = next(r for r in queue if r["id"] == awaiting_clarification.pk)
    assert row["status"] == EventStatus.SUBMITTED
    detail = api.get(detail_url(awaiting_clarification)).data
    assert detail["clarifications"][0]["resolved_at"] is not None


@pytest.mark.django_db
def test_ac3_several_clarification_rounds_are_all_kept(
    api, organiser, coordinator, awaiting_clarification
):
    api.force_authenticate(organiser)
    api.post(submit_url(awaiting_clarification))
    api.force_authenticate(coordinator)
    second = api.post(
        clarify_url(awaiting_clarification), {"message": "Which projector model?"}, format="json"
    )

    assert second.status_code == 200
    messages = [c["message"] for c in second.data["clarifications"]]
    assert messages == ["Which projector model?", "How many attendees need wheelchair access?"]
    assert (
        Notification.objects.filter(
            recipient=organiser, event=awaiting_clarification, kind=NotificationKind.CLARIFICATION
        ).count()
        == 2
    )


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"message": ""}, {"message": "   "}])
def test_ac4_a_clarification_request_without_a_message_is_rejected(
    signed_in_coordinator, my_submitted_event, payload
):
    response = signed_in_coordinator.post(clarify_url(my_submitted_event), payload, format="json")

    assert response.status_code == 400
    assert "message" in response.data
    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED
    assert not ClarificationRequest.objects.exists()
    assert not Notification.objects.filter(kind=NotificationKind.CLARIFICATION).exists()


@pytest.mark.django_db
def test_an_unknown_field_name_is_rejected(signed_in_coordinator, my_submitted_event):
    response = signed_in_coordinator.post(
        clarify_url(my_submitted_event),
        {"message": "Please fix", "fields": ["not_a_field"]},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.UNDER_REVIEW, EventStatus.APPROVED, EventStatus.CONFIRMED, EventStatus.REJECTED],
)
def test_clarification_can_only_be_requested_on_a_submitted_request(
    signed_in_coordinator, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(
        clarify_url(event), {"message": "Please clarify"}, format="json"
    )

    assert response.status_code == 409
    assert AuditLog.objects.filter(
        action=f"POST /api/events/{event.pk}/request-clarification/"
    ).exists()


@pytest.mark.django_db
def test_only_the_assigned_coordinator_can_request_clarification(
    api, other_coordinator, organiser, my_submitted_event
):
    api.force_authenticate(other_coordinator)
    assert (
        api.post(clarify_url(my_submitted_event), {"message": "?"}, format="json").status_code
        == 403
    )

    api.force_authenticate(organiser)
    assert (
        api.post(clarify_url(my_submitted_event), {"message": "?"}, format="json").status_code
        == 403
    )

    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_another_organisation_cannot_edit_a_request_awaiting_clarification(
    api, other_organiser, awaiting_clarification
):
    api.force_authenticate(other_organiser)

    response = api.patch(detail_url(awaiting_clarification), {"name": "Hijack"}, format="json")

    assert response.status_code == 403
