"""Week 7 change 5 - the Event Coordinator Lead assigns submitted requests.

Supersedes the automatic random assignment of SCRUM-51 (AC1, AC2 and AC5 no longer
apply: "it is now manually assigned by the lead and no more system auto-assignment",
clarification session). The submission regressions SCRUM-51 introduced still hold.

CR5-AC1  A submitted request enters the unassigned queue; nobody is assigned.
CR5-AC2  Every Lead sees the unassigned queue; nobody else does.
CR5-AC3  A Lead assigns a coordinator, who becomes the point of contact.
CR5-AC4  A Lead reassigns, including after arrangements are confirmed.
CR5-AC5  Coordinators see and manage only events assigned to them.
CR5-AC6  Leads see all assignments and the ones they supervise.
CR5-AC7  The coordinator, any previous coordinator and the client are notified.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus, InvalidTransition
from apps.events.models import CoordinatorAssignment, EventRequest
from apps.events.services import MissingMandatoryFields, submit_event
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event

pytestmark = pytest.mark.django_db


def assign(api, event, coordinator):
    return api.post(
        f"/api/events/{event.pk}/assign/", {"coordinator": coordinator.pk}, format="json"
    )


# --- CR5-AC1 / AC2 - the unassigned queue -----------------------------------------


def test_cr5_ac1_submission_is_not_assigned_automatically(
    signed_in_organiser, complete_draft, coordinator
):
    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")

    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert complete_draft.status == EventStatus.SUBMITTED
    assert response.data["assignment_requires_attention"] is True
    assert complete_draft.status_history.count() == 1


def test_cr5_ac1_the_client_and_every_lead_are_told(complete_draft, organiser, lead, coordinator):
    second_lead = User.objects.create_user(
        username="lead2", email="lead2@connectsphere.example", role=Role.COORDINATOR_LEAD
    )

    submit_event(complete_draft, organiser)

    notices = Notification.objects.filter(event=complete_draft)
    assert set(notices.values_list("recipient_id", flat=True)) == {
        organiser.pk,
        lead.pk,
        second_lead.pk,
    }
    assert not notices.filter(recipient=coordinator).exists()
    assert "Coordinator Lead" in notices.get(recipient=organiser).message


def test_cr5_ac2_every_lead_sees_the_unassigned_queue(api, organiser, lead, coordinator):
    waiting = make_event(organiser, status=EventStatus.SUBMITTED, name="Waiting")
    make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator, name="Taken")
    second_lead = User.objects.create_user(
        username="lead2", email="lead2@connectsphere.example", role=Role.COORDINATOR_LEAD
    )

    for who in (lead, second_lead):
        api.force_authenticate(who)
        rows = api.get("/api/events/queue/").data
        assert [row["name"] for row in rows] == [waiting.name]


@pytest.mark.parametrize("role", ["coordinator", "organiser", "venue_staff", "safety_officer"])
def test_cr5_ac2_only_leads_open_the_queue(api, request, role):
    api.force_authenticate(request.getfixturevalue(role))

    assert api.get("/api/events/queue/").status_code == 403
    assert AuditLog.objects.filter(action="GET /api/events/queue/", allowed=False).exists()


# --- CR5-AC3 - assigning ----------------------------------------------------------


def test_cr5_ac3_a_lead_assigns_a_coordinator(signed_in_lead, organiser, lead, coordinator):
    event = make_event(organiser, status=EventStatus.SUBMITTED, assignment_requires_attention=True)

    response = assign(signed_in_lead, event, coordinator)

    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert event.coordinator == coordinator
    assert event.assigned_by == lead
    assert event.assigned_at is not None
    assert event.assignment_requires_attention is False
    [row] = CoordinatorAssignment.objects.filter(event=event)
    assert (row.previous_coordinator, row.coordinator, row.changed_by) == (None, coordinator, lead)


def test_cr5_ac3_the_client_sees_the_coordinator_name_and_contact(
    api, organiser, lead, coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)
    assign(api, event, coordinator)

    api.force_authenticate(organiser)
    response = api.get(f"/api/events/{event.pk}/")

    assert response.data["coordinator_name"] == coordinator.get_full_name()
    assert response.data["coordinator_email"] == coordinator.email


def test_cr5_ac3_name_falls_back_to_email(api, organiser, lead, coordinator):
    coordinator.first_name = coordinator.last_name = ""
    coordinator.save()
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)

    assert assign(api, event, coordinator).data["coordinator_name"] == coordinator.email


@pytest.mark.parametrize("problem", ["inactive", "wrong_role"])
def test_cr5_ac3_only_an_active_coordinator_can_be_assigned(
    signed_in_lead, organiser, coordinator, problem
):
    if problem == "inactive":
        coordinator.is_active = False
    else:
        coordinator.role = Role.VENUE_STAFF
    coordinator.save()
    event = make_event(organiser, status=EventStatus.SUBMITTED)

    response = assign(signed_in_lead, event, coordinator)

    assert response.status_code == 400
    event.refresh_from_db()
    assert event.coordinator is None


@pytest.mark.parametrize("role", ["coordinator", "organiser", "safety_officer"])
def test_cr5_ac3_only_a_lead_can_assign(api, request, organiser, coordinator, role):
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(request.getfixturevalue(role))

    assert assign(api, event, coordinator).status_code == 403
    event.refresh_from_db()
    assert event.coordinator is None


def test_cr5_ac3_the_coordinator_list_shows_availability_and_workload(
    signed_in_lead, organiser, coordinator, second_coordinator
):
    make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    make_event(organiser, status=EventStatus.COMPLETED, coordinator=coordinator)
    second_coordinator.coordinator_available = False
    second_coordinator.save()

    rows = {row["email"]: row for row in signed_in_lead.get("/api/coordinators/").data}

    assert rows[coordinator.email]["active_events"] == 1
    assert rows[second_coordinator.email]["available"] is False


def test_cr5_ac3_coordinators_cannot_list_coordinators(signed_in_coordinator):
    assert signed_in_coordinator.get("/api/coordinators/").status_code == 403


# --- CR5-AC4 - reassigning --------------------------------------------------------


@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_cr5_ac4_a_lead_reassigns_even_after_arrangements_are_confirmed(
    signed_in_lead, organiser, coordinator, second_coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_lead.post(
        f"/api/events/{event.pk}/reassign/", {"coordinator": second_coordinator.pk}, format="json"
    )

    assert response.status_code == 200
    event.refresh_from_db()
    assert event.coordinator == second_coordinator
    assert event.status == status
    assert CoordinatorAssignment.objects.get(event=event).previous_coordinator == coordinator


@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_cr5_ac4_a_closed_event_cannot_be_reassigned(
    signed_in_lead, organiser, coordinator, second_coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    assert assign(signed_in_lead, event, second_coordinator).status_code == 409


def test_cr5_ac4_the_same_coordinator_is_refused(signed_in_lead, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)

    assert assign(signed_in_lead, event, coordinator).status_code == 400


def test_cr5_ac4_drafts_cannot_be_assigned(signed_in_lead, complete_draft, coordinator):
    assert assign(signed_in_lead, complete_draft, coordinator).status_code == 403


# --- CR5-AC5 - coordinators manage only their own events --------------------------


def test_cr5_ac5_a_coordinator_lists_only_their_own_events(
    signed_in_coordinator, organiser, coordinator, second_coordinator
):
    mine = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    make_event(organiser, status=EventStatus.PLANNING, coordinator=second_coordinator)
    make_event(organiser, status=EventStatus.SUBMITTED)

    rows = signed_in_coordinator.get("/api/events/").data

    assert [row["id"] for row in rows] == [mine.pk]


def test_cr5_ac5_a_coordinator_cannot_open_someone_elses_event(
    signed_in_coordinator, organiser, second_coordinator
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=second_coordinator)

    response = signed_in_coordinator.get(f"/api/events/{other.pk}/")

    assert response.status_code == 403
    assert list(response.data) == ["detail"]
    assert AuditLog.objects.filter(object_id=str(other.pk), allowed=False).exists()


def test_cr5_ac5_a_coordinator_cannot_act_on_an_unassigned_request(
    signed_in_coordinator, organiser
):
    waiting = make_event(organiser, status=EventStatus.SUBMITTED)

    assert signed_in_coordinator.post(f"/api/events/{waiting.pk}/approve/").status_code == 403
    waiting.refresh_from_db()
    assert waiting.status == EventStatus.SUBMITTED


# --- CR5-AC6 - leads see every assignment ------------------------------------------


def test_cr5_ac6_leads_see_all_assignments_and_the_ones_they_supervise(
    api, organiser, lead, coordinator, second_coordinator
):
    other_lead = User.objects.create_user(
        username="lead2", email="lead2@connectsphere.example", role=Role.COORDINATOR_LEAD
    )
    mine = make_event(organiser, status=EventStatus.SUBMITTED, name="Mine")
    theirs = make_event(organiser, status=EventStatus.SUBMITTED, name="Theirs")
    api.force_authenticate(lead)
    assign(api, mine, coordinator)
    api.force_authenticate(other_lead)
    assign(api, theirs, second_coordinator)

    api.force_authenticate(lead)
    everything = api.get("/api/events/assignments/").data
    supervised = api.get("/api/events/assignments/?supervised=mine").data

    assert {row["name"] for row in everything} == {"Mine", "Theirs"}
    assert [row["name"] for row in supervised] == ["Mine"]
    assert supervised[0]["coordinator_email"] == coordinator.email
    assert supervised[0]["assigned_by_name"] == lead.get_full_name()


def test_cr5_ac6_leads_read_any_submitted_event(api, organiser, lead, second_coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=second_coordinator)
    api.force_authenticate(lead)

    assert api.get(f"/api/events/{event.pk}/").status_code == 200
    assert api.get("/api/events/").data[0]["id"] == event.pk
    assert api.patch(f"/api/events/{event.pk}/", {"name": "x"}, format="json").status_code == 403


def test_cr5_ac6_only_leads_see_the_assignment_overview(signed_in_coordinator):
    assert signed_in_coordinator.get("/api/events/assignments/").status_code == 403


# --- CR5-AC7 - notifications -------------------------------------------------------


def test_cr5_ac7_assignment_notifies_the_coordinator_and_the_client(
    signed_in_lead, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED)

    assign(signed_in_lead, event, coordinator)

    notices = Notification.objects.filter(event=event, kind=NotificationKind.ASSIGNMENT)
    assert set(notices.values_list("recipient_id", flat=True)) == {organiser.pk, coordinator.pk}
    assert coordinator.email in notices.get(recipient=organiser).message
    assert organiser.email in notices.get(recipient=coordinator).message


def test_cr5_ac7_reassignment_also_tells_the_previous_coordinator(
    signed_in_lead, organiser, coordinator, second_coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    assign(signed_in_lead, event, coordinator)

    assign(signed_in_lead, event, second_coordinator)

    notices = Notification.objects.filter(event=event, kind=NotificationKind.REASSIGNED)
    assert set(notices.values_list("recipient_id", flat=True)) == {
        organiser.pk,
        coordinator.pk,
        second_coordinator.pk,
    }
    assert "no longer coordinate" in notices.get(recipient=coordinator).message


def test_cr5_ac7_assigning_back_to_a_former_coordinator_does_not_fail(
    signed_in_lead, organiser, coordinator, second_coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    for who in (coordinator, second_coordinator, coordinator):
        assert assign(signed_in_lead, event, who).status_code == 200
    assert event.assignment_history.count() == 3


# --- submission regressions carried over from SCRUM-51 ---------------------------


def test_incomplete_submission_does_not_notify(incomplete_draft, organiser, lead):
    with pytest.raises(MissingMandatoryFields):
        submit_event(incomplete_draft, organiser)
    incomplete_draft.refresh_from_db()
    assert incomplete_draft.is_draft
    assert Notification.objects.count() == 0


def test_repeated_stale_submission_is_refused(complete_draft, organiser, lead):
    stale = EventRequest.objects.get(pk=complete_draft.pk)
    submit_event(complete_draft, organiser)
    with pytest.raises(InvalidTransition):
        submit_event(stale, organiser)
    stale.refresh_from_db()
    assert stale.status_history.count() == 1
    assert Notification.objects.count() == 2


def test_notification_failure_rolls_back_entire_submission(complete_draft, organiser, lead):
    with patch.object(
        Notification.objects, "bulk_create", side_effect=RuntimeError("storage error")
    ):
        with pytest.raises(RuntimeError, match="storage error"):
            submit_event(complete_draft, organiser)
    complete_draft.refresh_from_db()
    assert complete_draft.is_draft
    assert complete_draft.status_history.count() == 0
    assert Notification.objects.count() == 0


def test_client_cannot_set_assignment_fields(signed_in_organiser, complete_draft, coordinator):
    response = signed_in_organiser.patch(
        f"/api/events/{complete_draft.pk}/",
        {"coordinator": coordinator.pk, "assignment_requires_attention": True},
        format="json",
    )
    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert not complete_draft.assignment_requires_attention


def test_notifications_are_recipient_only(api, complete_draft, organiser, lead, other_organiser):
    submit_event(complete_draft, organiser)
    assert api.get("/api/notifications/").status_code == 403
    assert AuditLog.objects.get(action="GET /api/notifications/").actor is None
    for user in (organiser, lead, other_organiser):
        api.force_authenticate(user)
        response = api.get("/api/notifications/")
        assert response.status_code == 200
        assert len(response.data) == (0 if user == other_organiser else 1)
        assert api.post("/api/notifications/", {}, format="json").status_code == 405


@pytest.mark.django_db(transaction=True)
def test_concurrent_submissions_submit_and_notify_only_once(complete_draft, organiser, lead):
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            event = EventRequest.objects.get(pk=complete_draft.pk)
            user = User.objects.get(pk=organiser.pk)
            barrier.wait(timeout=10)
            try:
                submit_event(event, user)
                return "submitted"
            except InvalidTransition:
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["refused", "submitted"]
    complete_draft.refresh_from_db()
    assert complete_draft.status_history.count() == 1
    assert Notification.objects.count() == 2
