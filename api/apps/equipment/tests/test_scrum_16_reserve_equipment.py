"""G16a: real request -> reserve -> availability; Safety rows are G04 preconditions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailability,
    TechnicalApproval,
)
from apps.equipment.reservations import EquipmentActionDenied, reserve
from apps.equipment.services import create_request
from apps.notifications.models import Notification
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import arrangement_version, confirmation_gaps
from conftest import make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


def request_item(event, stock, coordinator, quantity=6):
    return create_request(
        event=event, requested_by=coordinator, equipment_type=stock.pk, quantity=quantity
    )


def reserve_as(api, actor, item, revision=None):
    api.force_authenticate(actor)
    revision = item.plan.revision if revision is None else revision
    return api.post(
        f"/api/equipment/requests/{item.pk}/reserve/",
        {"expected_revision": revision},
        format="json",
    )


def test_s16_01_ac1_ac2_ac5_reserve_real_request_and_persist_approval_notice(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    before = timezone.now()
    response = reserve_as(api, tech, item)
    assert response.status_code == 200, response.data
    row = EquipmentReservation.objects.get(request=item)
    assert (row.quantity, row.starts_at, row.ends_at, row.reserved_by_id) == (
        6,
        event.preferred_start,
        event.preferred_end,
        tech.pk,
    )
    assert row.reserved_at >= before
    item.refresh_from_db()
    assert item.status == "RESERVED"
    plan = EquipmentPlan.objects.get(event=event)
    approval = TechnicalApproval.objects.get(plan=plan, status="APPROVED")
    assert (approval.plan_revision, approval.approved_by_id) == (plan.revision, tech.pk)
    assert (
        EquipmentHistory.objects.filter(reservation=row, action="RESERVED", actor=tech).count() == 1
    )
    assert (
        Notification.objects.filter(
            event=event, recipient=coordinator, kind="EQUIPMENT_UPDATED"
        ).count()
        == 1
    )
    other = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_start,
        preferred_end=event.preferred_end,
    )
    api.force_authenticate(coordinator)
    data = api.get(f"/api/events/{other.pk}/equipment-availability/").data
    assert data["equipment"][0]["available_quantity"] == 4
    assert data["equipment"][0]["reserved_for_other_events"] == 6


@pytest.mark.parametrize(
    "case,unavailable,retired",
    [("damaged", 5, False), ("maintenance", 5, False), ("retired", 0, True)],
)
def test_s16_02_ac3_ac4_unavailable_stock_refuses_without_mutation(
    api, event, stock, coordinator, tech, case, unavailable, retired
):
    item = request_item(event, stock, coordinator)
    if unavailable:
        EquipmentUnavailability.objects.create(
            equipment_type=stock,
            quantity=unavailable,
            cause="DAMAGED" if case == "damaged" else "MAINTENANCE",
            reason="Out of action",
            reported_by=tech,
        )
    stock.in_service = not retired
    stock.save()
    count = EquipmentHistory.objects.count()
    response = reserve_as(api, tech, item)
    assert response.status_code == 409
    assert response.data["available_quantity"] == (0 if retired else 5)
    assert EquipmentReservation.objects.count() == TechnicalApproval.objects.count() == 0
    assert EquipmentHistory.objects.count() == count


def test_s16_03_ac2_half_open_period_and_exact_stock(api, event, stock, coordinator, tech):
    first = request_item(event, stock, coordinator, 10)
    assert reserve_as(api, tech, first).status_code == 200
    adjacent = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_end,
        preferred_end=event.preferred_end + timezone.timedelta(hours=1),
    )
    next_item = request_item(adjacent, stock, coordinator, 10)
    assert reserve_as(api, tech, next_item).status_code == 200
    overlap = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_end - timezone.timedelta(seconds=1),
        preferred_end=event.preferred_end,
    )
    overlapping_item = request_item(overlap, stock, coordinator, 1)
    response = reserve_as(api, tech, overlapping_item)
    assert response.status_code == 409 and response.data["available_quantity"] == 0


def test_s16_04_multi_item_approval_only_after_entire_plan_is_reserved(
    api, event, stock, coordinator, tech
):
    first = request_item(event, stock, coordinator, 2)
    second_stock = EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=3)
    second = request_item(event, second_stock, coordinator, 3)
    plan = EquipmentPlan.objects.get(event=event)
    assert reserve_as(api, tech, first, plan.revision).status_code == 200
    assert not TechnicalApproval.objects.filter(status="APPROVED").exists()
    plan.refresh_from_db()
    assert reserve_as(api, tech, second, plan.revision).status_code == 200
    assert TechnicalApproval.objects.filter(status="APPROVED").count() == 1


@pytest.mark.parametrize("revision", [None, True, "1", -1, 0, 1.2])
def test_s16_05_missing_invalid_or_stale_revision(api, event, stock, coordinator, tech, revision):
    item = request_item(event, stock, coordinator)
    api.force_authenticate(tech)
    response = api.post(
        f"/api/equipment/requests/{item.pk}/reserve/",
        {"expected_revision": revision},
        format="json",
    )
    assert response.status_code in (400, 409)
    assert not EquipmentReservation.objects.exists()


def test_s16_06_replay_never_double_reserves(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator)
    assert reserve_as(api, tech, item).status_code == 200
    assert reserve_as(api, tech, item).status_code == 409
    plan = EquipmentPlan.objects.get(event=event)
    assert reserve_as(api, tech, item, plan.revision).status_code == 409
    assert EquipmentReservation.objects.count() == 1


@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_ORGANISER,
        Role.EVENT_COORDINATOR,
        Role.EVENT_COORDINATOR_LEAD,
        Role.VENUE_STAFF,
        Role.ATTENDEE,
        Role.SAFETY_OFFICER,
    ],
)
def test_s16_07_non_technical_roles_refused_and_audited(api, event, stock, coordinator, tech, role):
    from conftest import _make_user

    item = request_item(event, stock, coordinator)
    actor = _make_user(f"reserve-{role}@example.com", role)
    assert reserve_as(api, actor, item).status_code == 403
    assert AuditLog.objects.filter(actor=actor, allowed=False).exists()
    with pytest.raises(EquipmentActionDenied):
        reserve(equipment_request=item, actor=actor, expected_revision=1)
    assert not EquipmentReservation.objects.exists()


@pytest.mark.parametrize(
    "status", ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "COMPLETED", "CANCELLED", "REJECTED"]
)
def test_s16_08_closed_status_refused(api, event, stock, coordinator, tech, status):
    item = request_item(event, stock, coordinator)
    event.status = status
    event.save()
    assert reserve_as(api, tech, item).status_code == 409


def test_s16_09_ac6_safety_superseded_and_confirmation_refused(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    check = SafetyCheck.objects.create(
        event=event,
        requested_by=coordinator,
        arrangement_version=arrangement_version(event),
        status=SafetyStatus.APPROVED,
        decided_by=tech,
        decided_at=timezone.now(),
    )
    event.status = EventStatus.CONFIRMED
    event.save()
    assert reserve_as(api, tech, item).status_code == 200
    check.refresh_from_db()
    event.refresh_from_db()
    assert check.status == "SUPERSEDED" and event.status == "PLANNING"
    assert any("Operational safety check" in gap for gap in confirmation_gaps(event))


def test_s16_10_rollback_includes_approval_history_and_notices(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    before = EquipmentHistory.objects.count()
    with patch(
        "apps.equipment.reservations.arrangements_changed",
        side_effect=RuntimeError("invalidation failed"),
    ):
        with pytest.raises(RuntimeError):
            reserve_as(api, tech, item)
    assert not EquipmentReservation.objects.exists()
    assert not TechnicalApproval.objects.exists()
    assert EquipmentHistory.objects.count() == before
    assert not Notification.objects.filter(kind="EQUIPMENT_UPDATED").exists()
    item.refresh_from_db()
    item.plan.refresh_from_db()
    assert item.status == "REQUESTED" and item.plan.revision == 1


def test_s16_11_no_equipment_needs_explicit_review(api, event, tech):
    api.force_authenticate(tech)
    path = f"/api/events/{event.pk}/approve-no-equipment/"
    assert api.post(path, {"expected_revision": 0}, format="json").status_code == 400
    response = api.post(
        path,
        {
            "expected_revision": 0,
            "acknowledged": True,
            "notes": "Venue provides all required facilities.",
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["technical_approval"]["no_equipment_required"] is True
    assert TechnicalApproval.objects.get().approved_by_id == tech.pk
    assert (
        api.post(
            path, {"expected_revision": 1, "acknowledged": True, "notes": "Replay"}, format="json"
        ).status_code
        == 409
    )


@pytest.mark.django_db(transaction=True)
def test_s16_12_concurrent_events_cannot_over_allocate(organiser, coordinator, tech, stock):
    stock.total_quantity = 8
    stock.save()
    items = []
    start = timezone.now() + timezone.timedelta(days=30)
    for name in ("A", "B"):
        event = make_event(
            organiser,
            name=name,
            status=EventStatus.PLANNING,
            coordinator=coordinator,
            preferred_start=start,
            preferred_end=start + timezone.timedelta(hours=2),
        )
        items.append(request_item(event, stock, coordinator))
    barrier = Barrier(2)

    def attempt(pk):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(tech)
            barrier.wait(timeout=10)
            return client.post(
                f"/api/equipment/requests/{pk}/reserve/", {"expected_revision": 1}, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [item.pk for item in items]))
    assert sorted(results) == [200, 409]
    assert EquipmentReservation.objects.count() == 1
    assert EquipmentReservation.objects.get().quantity == 6


@pytest.mark.parametrize("invalid", ["missing", "reversed", "elapsed"])
def test_s16_13_invalid_or_elapsed_event_dates_refused(
    api, event, stock, coordinator, tech, invalid
):
    item = request_item(event, stock, coordinator)
    if invalid == "missing":
        event.preferred_start = None
    elif invalid == "reversed":
        event.preferred_end = event.preferred_start
    else:
        event.preferred_start = timezone.now() - timezone.timedelta(hours=2)
        event.preferred_end = timezone.now() - timezone.timedelta(hours=1)
    event.save()
    assert reserve_as(api, tech, item).status_code == 409
    assert not EquipmentReservation.objects.exists()


@pytest.mark.parametrize(
    "acknowledged,notes", [(False, "Checked"), ("true", "Checked"), (True, "  "), (True, 5)]
)
def test_s16_14_no_equipment_invalid_review_is_atomic(api, event, tech, acknowledged, notes):
    api.force_authenticate(tech)
    response = api.post(
        f"/api/events/{event.pk}/approve-no-equipment/",
        {"expected_revision": 0, "acknowledged": acknowledged, "notes": notes},
        format="json",
    )
    assert response.status_code == 400
    assert not EquipmentPlan.objects.filter(event=event).exists()


def test_s16_15_no_equipment_cannot_ignore_existing_request(api, event, stock, coordinator, tech):
    request_item(event, stock, coordinator)
    api.force_authenticate(tech)
    response = api.post(
        f"/api/events/{event.pk}/approve-no-equipment/",
        {"expected_revision": 1, "acknowledged": True, "notes": "Checked"},
        format="json",
    )
    assert response.status_code == 409
    assert not TechnicalApproval.objects.exists()


def test_s16_16_plan_reads_are_scoped_and_include_only_technical_fields(
    api, event, stock, coordinator, tech, second_coordinator, organiser
):
    path = f"/api/events/{event.pk}/equipment-plan/"
    assert api.get(path).status_code == 403
    api.force_authenticate(second_coordinator)
    assert api.get(path).status_code == 403
    api.force_authenticate(organiser)
    assert api.get(path).status_code == 403
    api.force_authenticate(coordinator)
    empty = api.get(path)
    assert empty.status_code == 200
    assert empty.data["revision"] == 0 and empty.data["requests"] == []
    assert "organisation" not in empty.data["event"] and "purpose" not in empty.data["event"]
    item = request_item(event, stock, coordinator)
    assert reserve_as(api, tech, item).status_code == 200
    data = api.get(path).data
    assert data["reservations"][0]["reserved_by_name"] == tech.email
    assert data["technical_approval"]["approved_by_name"] == tech.email
    event.status = EventStatus.DRAFT
    event.save()
    assert api.get(path).status_code == 403


def test_s16_17_technical_plan_list_excludes_private_and_closed_events(
    api, event, organiser, coordinator, tech
):
    private = make_event(organiser)
    closed = make_event(organiser, status=EventStatus.COMPLETED)
    api.force_authenticate(tech)
    assert api.get("/api/equipment/plans/").data == [{"id": event.pk, "name": event.name}]
    api.force_authenticate(coordinator)
    assert api.get("/api/equipment/plans/").status_code == 403
    assert private.pk != closed.pk


def test_s16_18_inactive_technical_actor_and_withdrawn_request_refused(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    tech.is_active = False
    tech.save()
    assert reserve_as(api, tech, item).status_code == 403
    tech.is_active = True
    tech.save()
    item.status = "WITHDRAWN"
    item.save()
    assert reserve_as(api, tech, item).status_code == 409
    assert not EquipmentReservation.objects.exists()


def test_s16_19_new_request_supersedes_previous_no_equipment_approval(
    api, event, stock, coordinator, tech
):
    api.force_authenticate(tech)
    assert (
        api.post(
            f"/api/events/{event.pk}/approve-no-equipment/",
            {"expected_revision": 0, "acknowledged": True, "notes": "Initial technical review"},
            format="json",
        ).status_code
        == 200
    )
    old = TechnicalApproval.objects.get()
    item = request_item(event, stock, coordinator)
    assert reserve_as(api, tech, item).status_code == 200
    old.refresh_from_db()
    assert old.status == "SUPERSEDED" and old.superseded_at is not None
    assert EquipmentHistory.objects.filter(action=EquipmentHistoryAction.SUPERSEDED).count() == 1
    assert TechnicalApproval.objects.filter(status="APPROVED").get().pk != old.pk


def test_s16_20_no_recipient_and_malformed_input_do_not_leak_or_mutate(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    api.force_authenticate(tech)
    assert (
        api.post(f"/api/equipment/requests/{item.pk}/reserve/", [], format="json").status_code
        == 400
    )
    event.coordinator = None
    event.save()
    assert reserve_as(api, tech, item).status_code == 200
    assert not Notification.objects.filter(kind="EQUIPMENT_UPDATED").exists()


def test_s16_21_incorrect_existing_reservation_period_cannot_approve_plan(
    api, event, stock, coordinator, tech
):
    first = request_item(event, stock, coordinator, 2)
    another_type = EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=3)
    second = request_item(event, another_type, coordinator, 2)
    assert reserve_as(api, tech, first, 2).status_code == 200
    # A stale pre-existing resource snapshot is a service-test precondition.
    EquipmentReservation.objects.filter(request=first).update(
        ends_at=event.preferred_end - timezone.timedelta(hours=1)
    )
    assert reserve_as(api, tech, second, 3).status_code == 200
    assert not TechnicalApproval.objects.filter(status="APPROVED").exists()
