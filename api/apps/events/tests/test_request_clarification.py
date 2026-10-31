"""SCRUM-49 - Request clarification or amendment from the Event Organiser.

SCRUM-92 (Sprint 3, gate G06) changed AC2-AC3: the Event Organiser no longer
edits and resubmits after submission. The assigned coordinator makes the agreed
edits on the client's behalf and resumes review; both sides record notes from
the offline clarification conversation. The original organiser edit/resubmit
tests are kept in Git history; these are their updated expectations.
"""

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import ClarificationComment, ClarificationRequest, EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from conftest import PASSWORD, make_event


def clarify_url(event):
    return f"/api/events/{event.pk}/request-clarification/"


def submit_url(event):
    return f"/api/events/{event.pk}/submit/"


def detail_url(event):
    return f"/api/events/{event.pk}/"


def resume_url(event):
    return f"/api/events/{event.pk}/resume-review/"


def notes_url(event):
    return f"/api/events/{event.pk}/clarification-notes/"


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
def test_ac2_the_coordinator_makes_the_agreed_edits_and_resumes_review(
    api, organiser, coordinator, awaiting_clarification
):
    # SCRUM-92 AC3 - the client can no longer edit or resubmit...
    api.force_authenticate(organiser)
    assert api.get(detail_url(awaiting_clarification)).data["is_editable"] is False
    refused_edit = api.patch(
        detail_url(awaiting_clarification),
        {"accessibility_needs": "Six wheelchair users; step-free access needed."},
        format="json",
    )
    refused_submit = api.post(submit_url(awaiting_clarification))
    assert refused_edit.status_code == 403
    assert refused_submit.status_code == 403
    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.accessibility_needs == ""
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW

    # ...the assigned coordinator makes the agreed edit and resumes review.
    api.force_authenticate(coordinator)
    assert api.get(detail_url(awaiting_clarification)).data["is_editable"] is True
    edited = api.patch(
        detail_url(awaiting_clarification),
        {"accessibility_needs": "Six wheelchair users; step-free access needed."},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.data["accessibility_needs"] == "Six wheelchair users; step-free access needed."
    resumed = api.post(resume_url(awaiting_clarification))
    assert resumed.status_code == 200
    assert resumed.data["status"] == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_ac2_the_organiser_still_cannot_delete_a_request_awaiting_clarification(
    api, organiser, awaiting_clarification
):
    api.force_authenticate(organiser)

    assert api.delete(detail_url(awaiting_clarification)).status_code == 403


@pytest.mark.django_db
def test_ac2_resuming_review_still_needs_the_mandatory_fields(
    api, coordinator, awaiting_clarification
):
    api.force_authenticate(coordinator)
    api.patch(detail_url(awaiting_clarification), {"purpose": ""}, format="json")

    response = api.post(resume_url(awaiting_clarification))

    assert response.status_code == 400
    assert response.data["missing_fields"] == ["purpose"]
    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW


@pytest.mark.django_db
def test_ac3_a_resumed_request_returns_to_the_queue_with_its_history(
    api, signed_in_coordinator, organiser, coordinator, awaiting_clarification
):
    original_submitted_at = awaiting_clarification.submitted_at
    api.force_authenticate(coordinator)
    api.post(resume_url(awaiting_clarification))

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
        recipient=organiser, event=awaiting_clarification, kind=NotificationKind.REVIEW_RESUMED
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
    api.force_authenticate(coordinator)
    api.post(resume_url(awaiting_clarification))
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


# SCRUM-92 - Record offline clarification conversations on the request. -------
# Case IDs follow the Sprint 3 guide: S3-SCRUM-92-<case>.


@pytest.mark.django_db
@pytest.mark.parametrize("author", ["coordinator", "organiser", "colleague"])
def test_s3_92_01_ac1_a_note_is_saved_with_author_and_time_and_the_other_party_notified(
    api, request, organiser, coordinator, acme, awaiting_clarification, author
):
    colleague = User.objects.create_user(
        username="colleague@acme.example",
        email="colleague@acme.example",
        password=PASSWORD,
        role=Role.EVENT_ORGANISER,
        organisation=acme,
        first_name="Cole",
        last_name="League",
    )
    writer = {"coordinator": coordinator, "organiser": organiser, "colleague": colleague}[author]
    api.force_authenticate(writer)

    response = api.post(
        notes_url(awaiting_clarification),
        {"body": "  Agreed by phone: six wheelchair users, ramp at entrance B.  "},
        format="json",
    )

    assert response.status_code == 201
    note = ClarificationComment.objects.get()
    assert note.body == "Agreed by phone: six wheelchair users, ramp at entrance B."
    assert note.author == writer
    assert note.created_at is not None
    assert note.clarification == ClarificationRequest.objects.get(event=awaiting_clarification)
    other_party = organiser if author == "coordinator" else coordinator
    notice = Notification.objects.get(kind=NotificationKind.CLARIFICATION_NOTE)
    assert notice.recipient == other_party
    assert "six wheelchair users" in notice.message
    shown = response.data["clarifications"][0]["comments"]
    assert [(c["body"], c["author_name"]) for c in shown] == [
        (note.body, writer.get_full_name()),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"body": ""}, {"body": "   "}])
def test_s3_92_02_ac2_an_empty_note_is_refused(
    signed_in_coordinator, awaiting_clarification, payload
):
    response = signed_in_coordinator.post(notes_url(awaiting_clarification), payload, format="json")

    assert response.status_code == 400
    assert "body" in response.data
    assert not ClarificationComment.objects.exists()
    assert not Notification.objects.filter(kind=NotificationKind.CLARIFICATION_NOTE).exists()


@pytest.mark.django_db
def test_s3_92_02_ac2_a_note_without_an_open_clarification_is_refused(
    api, coordinator, organiser, my_submitted_event, awaiting_clarification
):
    no_clarification = make_event(
        organiser, status=EventStatus.SUBMITTED, coordinator=coordinator, name="Other"
    )
    api.force_authenticate(coordinator)

    never_asked = api.post(notes_url(no_clarification), {"body": "A note"}, format="json")
    api.post(resume_url(awaiting_clarification))
    already_answered = api.post(
        notes_url(awaiting_clarification), {"body": "Too late"}, format="json"
    )

    assert never_asked.status_code == 409
    assert already_answered.status_code == 409
    assert not ClarificationComment.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["other_coordinator", "other_organiser", "lead", "attendee"])
def test_s3_92_02_ac2_nobody_but_the_client_and_assigned_coordinator_adds_notes(
    api, request, awaiting_clarification, who
):
    api.force_authenticate(request.getfixturevalue(who))

    response = api.post(notes_url(awaiting_clarification), {"body": "Intruder"}, format="json")

    assert response.status_code == 403
    assert not ClarificationComment.objects.exists()


@pytest.mark.django_db
def test_s3_92_03_ac3_the_organiser_cannot_edit_any_submitted_request(api, organiser, coordinator):
    api.force_authenticate(organiser)
    for status in (EventStatus.SUBMITTED, EventStatus.UNDER_REVIEW, EventStatus.APPROVED):
        event = make_event(organiser, status=status, coordinator=coordinator)
        response = api.patch(detail_url(event), {"name": "Changed by client"}, format="json")
        assert response.status_code == 403, status
        event.refresh_from_db()
        assert event.name == "Regional Partner Conference"
        assert AuditLog.objects.filter(
            actor=organiser, action=f"PATCH {detail_url(event)}", allowed=False
        ).exists()


@pytest.mark.django_db
def test_s3_92_04_ac4_resuming_keeps_the_clarification_and_its_notes(
    api, organiser, coordinator, awaiting_clarification
):
    api.force_authenticate(organiser)
    api.post(notes_url(awaiting_clarification), {"body": "Called Cora on Monday."}, format="json")
    api.force_authenticate(coordinator)
    api.post(notes_url(awaiting_clarification), {"body": "Confirmed six users."}, format="json")

    resumed = api.post(resume_url(awaiting_clarification))

    assert resumed.status_code == 200
    assert resumed.data["status"] == EventStatus.SUBMITTED
    clarification = resumed.data["clarifications"][0]
    assert clarification["resolved_at"] is not None
    assert [c["body"] for c in clarification["comments"]] == [
        "Called Cora on Monday.",
        "Confirmed six users.",
    ]
    # A fresh read by the client sees the same history.
    api.force_authenticate(organiser)
    fresh = api.get(detail_url(awaiting_clarification)).data["clarifications"][0]
    assert len(fresh["comments"]) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["other_coordinator", "organiser", "lead"])
def test_s3_92_04_only_the_assigned_coordinator_resumes_review(
    api, request, awaiting_clarification, who
):
    api.force_authenticate(request.getfixturevalue(who))

    response = api.post(resume_url(awaiting_clarification))

    assert response.status_code == 403
    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW


@pytest.mark.django_db
def test_s3_92_04_review_can_only_be_resumed_from_awaiting_clarification(
    signed_in_coordinator, my_submitted_event
):
    response = signed_in_coordinator.post(resume_url(my_submitted_event))

    assert response.status_code == 409
    my_submitted_event.refresh_from_db()
    assert my_submitted_event.status == EventStatus.SUBMITTED


# Service-level guards behind the API permission checks (defence in depth).


@pytest.mark.django_db
def test_s3_92_services_refuse_a_non_party_even_when_called_directly(
    other_coordinator, other_organiser, awaiting_clarification
):
    from apps.events.services import (
        NotAssignedCoordinator,
        NotClarificationParty,
        add_clarification_comment,
        resume_review,
    )

    with pytest.raises(NotAssignedCoordinator):
        resume_review(awaiting_clarification, other_coordinator)
    for outsider in (other_coordinator, other_organiser):
        with pytest.raises(NotClarificationParty):
            add_clarification_comment(awaiting_clarification, outsider, "Intruder")
    awaiting_clarification.refresh_from_db()
    assert awaiting_clarification.status == EventStatus.UNDER_REVIEW
    assert not ClarificationComment.objects.exists()


@pytest.mark.django_db
def test_s3_92_a_note_describes_itself_for_the_admin(api, coordinator, awaiting_clarification):
    api.force_authenticate(coordinator)
    api.post(notes_url(awaiting_clarification), {"body": "Noted."}, format="json")
    note = ClarificationComment.objects.get()

    assert str(note) == f"Note on clarification {note.clarification_id} by {coordinator.pk}"
