"""SCRUM-61 - Update event information during planning (Sprint 3, gate G06).

As an Event Coordinator, I want to update an event's information as planning
progresses, so that everyone works from one current version instead of separate
spreadsheets and notes.

Case IDs follow the Sprint 3 guide: S3-SCRUM-61-<case>.
"""

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.safety.models import SafetyStatus
from apps.safety.tests.conftest import make_check
from conftest import PASSWORD, make_event

EDITS = {
    "name": "Regional Partner Summit 2027",
    "description": "Two keynote sessions and a networking lunch.",
    "accessibility_needs": "Six wheelchair users; hearing loop.",
}


def detail_url(event):
    return f"/api/events/{event.pk}/"


@pytest.fixture
def safety_officer(db):
    return User.objects.create_user(
        username="safety@connectsphere.example",
        email="safety@connectsphere.example",
        password=PASSWORD,
        role=Role.SAFETY_OFFICER,
    )


# S3-SCRUM-61-01 - AC1/AC4/AC5: the assigned coordinator edits up to Planning. --


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.SUBMITTED, EventStatus.UNDER_REVIEW, EventStatus.APPROVED, EventStatus.PLANNING],
)
def test_s3_61_01_ac1_ac5_the_assigned_coordinator_edits_and_everyone_sees_it(
    api, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), EDITS, format="json")

    assert response.status_code == 200
    event.refresh_from_db()
    for field, value in EDITS.items():
        assert getattr(event, field) == value
    assert event.status == status
    # AC1 - shown to the other users with access, on a fresh read.
    api.force_authenticate(organiser)
    fresh = api.get(detail_url(event)).data
    assert {field: fresh[field] for field in EDITS} == EDITS


@pytest.mark.django_db
def test_s3_61_01_ac4_the_editor_and_time_are_recorded(api, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    before = event.updated_at
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), {"name": "Renamed in planning"}, format="json")

    event.refresh_from_db()
    assert event.updated_by == coordinator
    assert event.updated_at > before
    assert response.data["updated_by_name"] == "Cora Coordinator"
    audit = AuditLog.objects.get(actor=coordinator, action=f"Event {event.pk} edited")
    assert audit.allowed is True
    assert audit.detail == "Changed: name"


@pytest.mark.django_db
def test_s3_61_01_ac4_a_save_that_changes_nothing_records_no_edit(api, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), {"name": event.name}, format="json")

    assert response.status_code == 200
    event.refresh_from_db()
    assert event.updated_by is None
    assert not AuditLog.objects.filter(action=f"Event {event.pk} edited").exists()


@pytest.mark.django_db
def test_s3_61_01_status_and_decision_fields_cannot_be_set_through_an_edit(
    api, organiser, coordinator, second_coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)

    api.patch(
        detail_url(event),
        {
            "status": EventStatus.CONFIRMED,
            "coordinator": second_coordinator.pk,
            "approved_by": coordinator.pk,
            "updated_by": second_coordinator.pk,
            "name": "Only this changes",
        },
        format="json",
    )

    event.refresh_from_db()
    assert event.name == "Only this changes"
    assert event.status == EventStatus.SUBMITTED
    assert event.coordinator == coordinator
    assert event.approved_by is None
    assert event.updated_by == coordinator


@pytest.mark.django_db
def test_s3_61_01_edits_are_still_validated(api, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.patch(
        detail_url(event),
        {"expected_attendance": 0, "preferred_end": event.preferred_start.isoformat()},
        format="json",
    )

    assert response.status_code == 400
    event.refresh_from_db()
    assert event.expected_attendance == 120


# S3-SCRUM-61-02 - AC2: anyone else is refused. --------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "who", ["second_coordinator", "lead", "venue_staff", "other_organiser", "attendee"]
)
def test_s3_61_02_ac2_anyone_but_the_assigned_coordinator_is_refused(
    api, request, organiser, coordinator, who
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    response = api.patch(detail_url(event), {"name": "Not allowed"}, format="json")

    assert response.status_code == 403
    event.refresh_from_db()
    assert event.name == "Regional Partner Conference"
    assert event.updated_by is None
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s3_61_02_ac2_a_previous_coordinator_loses_edit_access_after_reassignment(
    api, organiser, coordinator, second_coordinator
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    event.coordinator = second_coordinator
    event.save(update_fields=["coordinator"])
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), {"name": "Stale edit"}, format="json")

    assert response.status_code == 403
    event.refresh_from_db()
    assert event.name == "Regional Partner Conference"


# S3-SCRUM-61-03 - AC3: Confirmed, Completed and Cancelled are not edited directly.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.CONFIRMED, EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED],
)
def test_s3_61_03_ac3_finished_or_confirmed_events_cannot_be_edited_directly(
    api, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), {"name": "Direct change"}, format="json")

    assert response.status_code == 403
    event.refresh_from_db()
    assert event.name == "Regional Partner Conference"
    assert event.status == status
    denial = AuditLog.objects.get(actor=coordinator, allowed=False)
    if status == EventStatus.CONFIRMED:
        assert denial.detail == "a Confirmed event changes only through a change request"
    api.force_authenticate(coordinator)
    assert api.get(detail_url(event)).data["is_editable"] is False


# S3-SCRUM-61-04 - AC6: the organiser edits drafts only. ------------------------


@pytest.mark.django_db
def test_s3_61_04_ac6_the_organiser_edits_their_draft_but_not_after_submission(
    api, organiser, coordinator
):
    draft = make_event(organiser)
    submitted = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(organiser)

    draft_edit = api.patch(detail_url(draft), {"name": "Draft renamed"}, format="json")
    submitted_edit = api.patch(detail_url(submitted), {"name": "Too late"}, format="json")

    assert draft_edit.status_code == 200
    assert draft_edit.data["is_editable"] is True
    draft.refresh_from_db()
    assert draft.name == "Draft renamed"
    assert draft.updated_by == organiser
    assert submitted_edit.status_code == 403
    assert api.get(detail_url(submitted)).data["is_editable"] is False


@pytest.mark.django_db
def test_s3_61_04_a_coordinator_cannot_see_or_edit_a_draft(api, organiser, coordinator):
    draft = make_event(organiser, coordinator=coordinator)
    api.force_authenticate(coordinator)

    assert api.patch(detail_url(draft), {"name": "No"}, format="json").status_code == 403


# S3-SCRUM-61-05 - integration with the Operational Safety Check (SCRUM-90). ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"expected_attendance": 150},
        {"preferred_start": "shift"},
    ],
)
def test_s3_61_05_editing_date_time_or_attendance_supersedes_an_approved_safety_check(
    api, organiser, coordinator, safety_officer, change
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    check = make_check(event, status=SafetyStatus.APPROVED, officer=safety_officer)
    if "preferred_start" in change:
        change = {
            "preferred_start": (event.preferred_start + timezone.timedelta(hours=1)).isoformat()
        }
    api.force_authenticate(coordinator)

    response = api.patch(detail_url(event), change, format="json")

    assert response.status_code == 200
    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED
    assert "changed" in check.superseded_reason


@pytest.mark.django_db
def test_s3_61_05_an_edit_that_leaves_the_arrangements_alone_keeps_the_safety_check(
    api, organiser, coordinator, safety_officer
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    check = make_check(event, status=SafetyStatus.APPROVED, officer=safety_officer)
    api.force_authenticate(coordinator)

    api.patch(detail_url(event), {"description": "Updated agenda"}, format="json")
    api.patch(detail_url(event), {"expected_attendance": event.expected_attendance}, format="json")

    check.refresh_from_db()
    assert check.status == SafetyStatus.APPROVED


@pytest.mark.django_db
@pytest.mark.parametrize("method, suffix", [("post", "submit/"), ("delete", "")])
def test_s3_61_02_other_writes_stay_closed_to_the_assigned_coordinator(
    api, organiser, coordinator, method, suffix
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = getattr(api, method)(f"{detail_url(event)}{suffix}")

    assert response.status_code == 403
    assert AuditLog.objects.get(actor=coordinator, allowed=False).detail == (
        "this action is not available to coordinators"
    )
    assert EventRequest.objects.filter(pk=event.pk, status=EventStatus.SUBMITTED).exists()


@pytest.mark.django_db
def test_s3_61_is_editable_without_a_signed_in_user_follows_the_draft_rule(organiser):
    from apps.events.serializers import EventRequestSerializer

    draft = make_event(organiser)
    submitted = make_event(organiser, status=EventStatus.SUBMITTED)

    assert EventRequestSerializer(draft).data["is_editable"] is True
    assert EventRequestSerializer(submitted).data["is_editable"] is False
