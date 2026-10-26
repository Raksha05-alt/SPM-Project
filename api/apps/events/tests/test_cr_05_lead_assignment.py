"""SCRUM-89 / SCRUM-53: manual allocation, access and atomic concurrency.

AC mapping and test evidence: docs/lead-assignment.md. Requires PostgreSQL.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import CoordinatorAssignment, EventRequest
from apps.events.services import (
    AssignmentConflict,
    InvalidCoordinator,
    NotAssignedCoordinator,
    NotCoordinatorLead,
    approve_event,
    assign_coordinator,
    reject_event,
    request_clarification,
)
from apps.notifications.models import Notification
from conftest import make_event

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_two_leads_can_swap_owners_of_different_events_without_deadlock(
    lead, coordinator, second_coordinator, submitted_event, organiser
):
    other = make_event(organiser, status=EventStatus.SUBMITTED)
    lead2 = User.objects.create_user(
        username="swap-lead", email="swaplead@example.com", role=Role.EVENT_COORDINATOR_LEAD
    )
    assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    assign_coordinator(other, second_coordinator.pk, lead2, 0)
    original = CoordinatorAssignment.objects.create
    both_targets_locked = Barrier(2)

    def create_after_both_targets_locked(**kwargs):
        both_targets_locked.wait(timeout=10)
        return original(**kwargs)

    def attempt(args):
        close_old_connections()
        try:
            event, target, actor = args
            assign_coordinator(event, target.pk, actor, 1)
        finally:
            close_old_connections()

    with patch.object(
        CoordinatorAssignment.objects, "create", side_effect=create_after_both_targets_locked
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(
                pool.map(
                    attempt,
                    [(submitted_event, second_coordinator, lead), (other, coordinator, lead2)],
                )
            )
    submitted_event.refresh_from_db()
    other.refresh_from_db()
    assert submitted_event.coordinator == second_coordinator
    assert other.coordinator == coordinator
    assert CoordinatorAssignment.objects.count() == 4
    assert Notification.objects.count() == 10


def test_occurrence_and_notice_uniqueness_at_database_boundary(lead, coordinator, submitted_event):
    occurrence = assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    with pytest.raises(IntegrityError), transaction.atomic():
        CoordinatorAssignment.objects.create(
            event=submitted_event, coordinator=coordinator, assigned_by=lead, revision=1
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Notification.objects.create(
            event=submitted_event,
            recipient=coordinator,
            assignment=occurrence,
            kind="ASSIGNMENT",
            message="duplicate",
        )
    assert CoordinatorAssignment.objects.count() == 1
    assert Notification.objects.count() == 2


@pytest.mark.parametrize(
    "decision,service,payload",
    [
        ("approve", "approve_event", {}),
        ("reject", "reject_event", {"reason": "No room"}),
        (
            "request-clarification",
            "request_clarification",
            {"message": "Please clarify", "fields": []},
        ),
    ],
)
def test_reassignment_between_permission_check_and_decision_is_denied_and_audited(
    api, lead, coordinator, second_coordinator, submitted_event, decision, service, payload
):
    from apps.events import views

    assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    original = getattr(views, service)

    def reassign_before_decision(event, actor, *args):
        assign_coordinator(event, second_coordinator.pk, lead, 1)
        return original(event, actor, *args)

    api.force_authenticate(coordinator)
    with patch.object(views, service, side_effect=reassign_before_decision):
        response = api.post(f"/api/events/{submitted_event.pk}/{decision}/", payload, format="json")
    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=coordinator, allowed=False).exists()
    submitted_event.refresh_from_db()
    assert submitted_event.coordinator == second_coordinator
    assert submitted_event.status == EventStatus.SUBMITTED


def test_lead_role_revoked_after_permissions_is_refused_and_audited(
    api, lead, coordinator, submitted_event
):
    from apps.events import views

    original = views.assign_coordinator

    def revoke_then_assign(*args, **kwargs):
        User.objects.filter(pk=lead.pk).update(role=Role.ATTENDEE)
        return original(*args, **kwargs)

    with patch.object(views, "assign_coordinator", side_effect=revoke_then_assign):
        response = assign(api, lead, submitted_event, coordinator)
    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=lead, allowed=False).exists()
    assert not submitted_event.assignment_history.exists()


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("post", "approve/"),
        ("post", "reject/"),
        ("post", "request-clarification/"),
        ("patch", ""),
        ("put", ""),
        ("delete", ""),
    ],
)
def test_lead_cannot_act_as_assigned_coordinator(
    api, lead, coordinator, submitted_event, method, suffix
):
    assign(api, lead, submitted_event, coordinator)
    response = getattr(api, method)(f"/api/events/{submitted_event.pk}/{suffix}", {}, format="json")
    assert response.status_code == 403
    submitted_event.refresh_from_db()
    assert submitted_event.status == EventStatus.SUBMITTED


def test_lead_lists_do_not_query_history_per_event(api, lead, organiser, django_assert_num_queries):
    for _ in range(6):
        make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)
    # One joined event query and one prefetched clarification query; no per-row history.
    with django_assert_num_queries(2):
        response = api.get("/api/events/")
    assert len(response.data) == 6


def assign(api, lead, event, coordinator, revision=0):
    api.force_authenticate(lead)
    return api.post(
        f"/api/events/{event.pk}/assign-coordinator/",
        {
            "coordinator_id": coordinator.pk,
            "expected_revision": revision,
        },
        format="json",
    )


def test_ac1_ac2_unassigned_queue_in_oldest_order_for_all_leads(api, lead, organiser, coordinator):
    first = make_event(organiser, status=EventStatus.SUBMITTED)
    second = make_event(organiser, status=EventStatus.SUBMITTED)
    make_event(organiser)
    make_event(organiser, status=EventStatus.COMPLETED)
    make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    for actor in (
        lead,
        User.objects.create_user(username="lead2", role=Role.EVENT_COORDINATOR_LEAD),
    ):
        api.force_authenticate(actor)
        response = api.get("/api/events/unassigned/")
        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [first.pk, second.pk]
        assert response.data[0]["organisation_name"] == organiser.organisation.name
        assert response.data[0]["supervising_lead"] is None


@pytest.mark.parametrize(
    "role", [None, *[r for r in Role.values if r != Role.EVENT_COORDINATOR_LEAD]]
)
@pytest.mark.parametrize(
    "endpoint", ["unassigned", "assignments", "coordinators", "assign-coordinator"]
)
def test_ac2_non_leads_refused_and_audited(api, submitted_event, coordinator, role, endpoint):
    actor = User.objects.create_user(username=f"actor-{role}", role=role) if role else None
    api.force_authenticate(actor)
    url = (
        f"/api/events/{submitted_event.pk}/assign-coordinator/"
        if endpoint == "assign-coordinator"
        else f"/api/events/{endpoint}/"
    )
    response = (
        api.post(url, {"coordinator_id": coordinator.pk, "expected_revision": 0}, format="json")
        if endpoint == "assign-coordinator"
        else api.get(url)
    )
    assert response.status_code == 403
    entry = AuditLog.objects.get(allowed=False)
    assert entry.actor == actor
    assert url in entry.action
    assert set(response.data) == {"detail"}
    assert submitted_event.assignment_history.count() == 0


def test_ac3_assignment_persists_history_contact_and_notices(
    api, lead, coordinator, submitted_event, organiser
):
    response = assign(api, lead, submitted_event, coordinator)
    assert response.status_code == 200
    assert response.data["coordinator"] == coordinator.pk
    assert response.data["supervising_lead"] == lead.pk
    assert response.data["assignment_revision"] == 1
    assert response.data["assignment_requires_attention"] is False
    history = submitted_event.assignment_history.get()
    assert history.previous_coordinator is None
    assert history.previous_supervising_lead is None
    assert history.assigned_by == lead
    assert history.assigned_at is not None
    assert response.data["assignment_history"][0]["assigned_by_name"] == lead.get_full_name()
    assert str(history) == f"Event {submitted_event.pk}: assignment {history.revision}"
    assert set(history.notifications.values_list("recipient_id", flat=True)) == {
        organiser.pk,
        coordinator.pk,
    }
    api.force_authenticate(organiser)
    detail = api.get(f"/api/events/{submitted_event.pk}/").data
    assert detail["coordinator_email"] == coordinator.email
    assert detail["coordinator_name"] == coordinator.get_full_name()
    assert "supervising_lead" not in detail and "assignment_history" not in detail
    assert AuditLog.objects.filter(allowed=True, action__contains="assign-coordinator").count() == 1


def test_ac4_reassignment_a_b_a_keeps_notices_and_previous_supervisor(
    api, lead, coordinator, second_coordinator, submitted_event, organiser
):
    lead2 = User.objects.create_user(username="lead2", role=Role.EVENT_COORDINATOR_LEAD)
    for revision, (actor, target) in enumerate(
        [(lead, coordinator), (lead2, second_coordinator), (lead, coordinator)]
    ):
        assert assign(api, actor, submitted_event, target, revision).status_code == 200
    rows = list(submitted_event.assignment_history.all())
    assert [row.revision for row in rows] == [3, 2, 1]
    assert rows[0].previous_supervising_lead == lead2
    assert rows[1].previous_supervising_lead == lead
    assert rows[1].previous_coordinator == coordinator
    assert rows[2].previous_coordinator is None
    assert rows[0].assigned_by == lead
    assert rows[0].previous_coordinator == second_coordinator
    assert [row.notifications.count() for row in rows] == [3, 3, 2]
    for user, count in [(organiser, 3), (coordinator, 3), (second_coordinator, 2)]:
        api.force_authenticate(user)
        assert len(api.get("/api/notifications/").data) == count
    with pytest.raises(ProtectedError):
        second_coordinator.delete()


@pytest.mark.parametrize("status", [EventStatus.COMPLETED, EventStatus.CANCELLED])
def test_ac4_closed_event_conflict_without_side_effects(api, lead, coordinator, organiser, status):
    event = make_event(organiser, status=status)
    assert assign(api, lead, event, coordinator).status_code == 409
    assert not event.assignment_history.exists()
    assert not Notification.objects.exists()
    assert AuditLog.objects.filter(allowed=False).count() == 1


@pytest.mark.parametrize(
    "status",
    [EventStatus.APPROVED, EventStatus.CONFIRMED, EventStatus.UNDER_REVIEW, EventStatus.REJECTED],
)
def test_ac4_other_submitted_states_allow_assignment(api, lead, coordinator, organiser, status):
    event = make_event(organiser, status=status)
    assert assign(api, lead, event, coordinator).status_code == 200
    event.refresh_from_db()
    assert event.status == status


def test_ac5_previous_owner_loses_list_detail_actions_shortlist(
    api, lead, coordinator, second_coordinator, submitted_event
):
    assert assign(api, lead, submitted_event, coordinator).status_code == 200
    api.force_authenticate(coordinator)
    assert api.get(f"/api/events/{submitted_event.pk}/").status_code == 200
    assert assign(api, lead, submitted_event, second_coordinator, 1).status_code == 200
    api.force_authenticate(coordinator)
    for path in ["/api/events/", "/api/events/queue/", "/api/events/mine/"]:
        assert api.get(path).data == []
    for method, suffix, payload in [
        ("get", "", {}),
        ("patch", "", {"name": "stolen"}),
        ("delete", "", {}),
        ("post", "approve/", {}),
        ("post", "reject/", {"reason": "No"}),
        ("post", "request-clarification/", {"message": "Why?", "fields": []}),
        ("get", "venue-shortlist/", {}),
    ]:
        response = getattr(api, method)(
            f"/api/events/{submitted_event.pk}/{suffix}", payload, format="json"
        )
        assert response.status_code == 403
    assert AuditLog.objects.filter(allowed=False, actor=coordinator).count() == 7
    api.force_authenticate(second_coordinator)
    assert api.get(f"/api/events/{submitted_event.pk}/").status_code == 200
    assert len(api.get("/api/events/mine/").data) == 1


def test_ac6_allocation_filters_and_validation(
    api, lead, coordinator, second_coordinator, organiser, submitted_event
):
    lead2 = User.objects.create_user(username="lead2", role=Role.EVENT_COORDINATOR_LEAD)
    assign(api, lead, submitted_event, coordinator)
    other = make_event(organiser, status=EventStatus.SUBMITTED)
    assign(api, lead2, other, second_coordinator)
    closed = make_event(
        organiser, status=EventStatus.COMPLETED, coordinator=coordinator, supervising_lead=lead
    )
    api.force_authenticate(lead)
    assert len(api.get("/api/events/assignments/").data) == 2
    assert [r["id"] for r in api.get("/api/events/assignments/?supervised_by=me").data] == [
        submitted_event.pk
    ]
    assert {
        r["id"] for r in api.get("/api/events/assignments/?supervised_by=me&active=false").data
    } == {submitted_event.pk, closed.pk}
    for params in ("active=no", "supervised_by=someone"):
        assert api.get(f"/api/events/assignments/?{params}").status_code == 400


def test_active_choices_availability_is_advisory(
    api, lead, coordinator, second_coordinator, submitted_event
):
    coordinator.coordinator_available = False
    coordinator.save()
    second_coordinator.is_active = False
    second_coordinator.save()
    api.force_authenticate(lead)
    choices = api.get("/api/events/coordinators/").data
    assert [row["id"] for row in choices] == [coordinator.pk]
    assert choices[0]["coordinator_available"] is False
    assert assign(api, lead, submitted_event, coordinator).status_code == 200


@pytest.mark.parametrize("target", ["inactive", "wrong_role", "missing"])
def test_invalid_target_no_change(api, lead, coordinator, submitted_event, target):
    if target == "inactive":
        coordinator.is_active = False
    elif target == "wrong_role":
        coordinator.role = Role.VENUE_STAFF
    coordinator.save()
    api.force_authenticate(lead)
    response = api.post(
        f"/api/events/{submitted_event.pk}/assign-coordinator/",
        {
            "coordinator_id": 999999 if target == "missing" else coordinator.pk,
            "expected_revision": 0,
        },
        format="json",
    )
    assert response.status_code == 400
    assert not submitted_event.assignment_history.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"coordinator_id": 1},
        {"coordinator_id": 1, "expected_revision": -1},
        {"coordinator_id": 0, "expected_revision": 0},
        {"coordinator_id": "abc", "expected_revision": 0},
    ],
)
def test_invalid_payload(api, lead, submitted_event, payload):
    api.force_authenticate(lead)
    assert (
        api.post(
            f"/api/events/{submitted_event.pk}/assign-coordinator/", payload, format="json"
        ).status_code
        == 400
    )
    assert not submitted_event.assignment_history.exists()


def test_draft_and_missing_event(api, lead, coordinator, complete_draft):
    assert assign(api, lead, complete_draft, coordinator).status_code == 403
    api.force_authenticate(lead)
    assert api.get("/api/events/999999/").status_code == 404


def test_same_target_noop_and_stale_conflict(api, lead, coordinator, submitted_event):
    assert assign(api, lead, submitted_event, coordinator).status_code == 200
    assert assign(api, lead, submitted_event, coordinator, 1).status_code == 200
    assert assign(api, lead, submitted_event, coordinator, 0).status_code == 409
    assert submitted_event.assignment_history.count() == 1
    assert Notification.objects.count() == 2


@pytest.mark.parametrize("failure", ["history", "notifications", "serialization"])
def test_assignment_failure_rolls_back(api, lead, coordinator, submitted_event, failure):
    paths = {
        "history": "apps.events.services.CoordinatorAssignment.objects.create",
        "notifications": "apps.events.services.Notification.objects.bulk_create",
        "serialization": "apps.events.views.LeadEventSerializer.to_representation",
    }
    with patch(paths[failure], side_effect=RuntimeError("save failed")):
        with pytest.raises(RuntimeError, match="save failed"):
            assign(api, lead, submitted_event, coordinator)
    submitted_event.refresh_from_db()
    assert submitted_event.coordinator is None
    assert submitted_event.assignment_revision == 0
    assert submitted_event.assignment_history.count() == Notification.objects.count() == 0
    assert not AuditLog.objects.filter(allowed=True).exists()


def test_service_rechecks_actor_and_target(lead, coordinator, submitted_event):
    User.objects.filter(pk=lead.pk).update(role=Role.ATTENDEE)
    with pytest.raises(NotCoordinatorLead):
        assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    User.objects.filter(pk=lead.pk).update(role=Role.EVENT_COORDINATOR_LEAD)
    User.objects.filter(pk=coordinator.pk).update(is_active=False)
    with pytest.raises(InvalidCoordinator):
        assign_coordinator(submitted_event, coordinator.pk, lead, 0)


@pytest.mark.parametrize("decision", ["approve", "reject", "clarify"])
def test_stale_decision_rechecks_current_owner(
    lead, coordinator, second_coordinator, submitted_event, decision
):
    assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    stale = EventRequest.objects.get(pk=submitted_event.pk)
    assign_coordinator(submitted_event, second_coordinator.pk, lead, 1)
    with pytest.raises(NotAssignedCoordinator):
        if decision == "approve":
            approve_event(stale, coordinator)
        elif decision == "reject":
            reject_event(stale, coordinator, "Reason")
        else:
            request_clarification(stale, coordinator, "Question")
    submitted_event.refresh_from_db()
    assert submitted_event.status == EventStatus.SUBMITTED
    assert submitted_event.status_history.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("already_assigned", [False, True])
def test_two_leads_same_revision_only_one_wins(
    lead, coordinator, second_coordinator, submitted_event, already_assigned
):
    lead2 = User.objects.create_user(username="lead2", role=Role.EVENT_COORDINATOR_LEAD)
    barrier = Barrier(2)
    if already_assigned:
        assign_coordinator(submitted_event, coordinator.pk, lead, 0)
    revision = int(already_assigned)
    third = User.objects.create_user(
        username="third", email="third@example.com", role=Role.EVENT_COORDINATOR
    )

    def attempt(args):
        close_old_connections()
        try:
            actor, target = args
            event = EventRequest.objects.get(pk=submitted_event.pk)
            barrier.wait(timeout=10)
            try:
                assign_coordinator(event, target.pk, actor, revision)
                return "saved"
            except AssignmentConflict:
                return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [(lead, third), (lead2, second_coordinator)]))
    assert sorted(results) == ["conflict", "saved"]
    submitted_event.refresh_from_db()
    assert (
        submitted_event.assignment_revision
        == submitted_event.assignment_history.count()
        == revision + 1
    )
    assert Notification.objects.count() == (5 if already_assigned else 2)
