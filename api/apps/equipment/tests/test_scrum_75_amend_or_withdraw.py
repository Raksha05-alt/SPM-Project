"""SCRUM-75: persisted amendment, exact surplus and atomic withdrawal."""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.equipment.models import EquipmentHistory, EquipmentPlan, EquipmentReservation
from apps.equipment.services import available_quantity
from apps.equipment.tests.test_scrum_16_reserve_equipment import event as event
from apps.equipment.tests.test_scrum_16_reserve_equipment import request_item, reserve_as
from apps.notifications.models import Notification
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import SAFETY_CHECK_ITEM, arrangement_version, confirmation_gaps

pytestmark = pytest.mark.django_db


def change(
    api, actor, item, *, withdraw=False, revision=None, quantity=3, requirements="Revised HDMI"
):
    api.force_authenticate(actor)
    revision = EquipmentPlan.objects.get(pk=item.plan_id).revision if revision is None else revision
    return api.post(
        f"/api/equipment/requests/{item.pk}/{'withdraw' if withdraw else 'amend'}/",
        {
            "expected_revision": revision,
            "quantity": quantity,
            "technical_requirements": requirements,
        },
        format="json",
    )


def test_s75_01_unreserved_persists_exact_values_and_staff_notice(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator, 5)
    start = timezone.now()
    response = change(api, coordinator, item)
    assert response.status_code == 200, response.data
    item.refresh_from_db()
    assert (item.quantity, item.technical_requirements, item.status) == (
        3,
        "Revised HDMI",
        "REQUESTED",
    )
    history = EquipmentHistory.objects.get(request=item, action="AMENDED")
    assert history.before["quantity"] == 5 and history.after["quantity"] == 3
    assert history.actor == coordinator and history.created_at >= start
    assert Notification.objects.filter(recipient=tech, kind="EQUIPMENT_UPDATED").count() == 1
    fresh = api.get(f"/api/events/{event.pk}/equipment-plan/").data
    assert fresh["requests"][0]["quantity"] == 3
    assert fresh["history"][0]["before"]["quantity"] == 5


def test_s75_02_reserved_reduction_releases_only_surplus_and_supersedes_safety(
    api, event, stock, coordinator, tech
):
    stock.total_quantity = 8
    stock.save()
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert available_quantity(stock, event.preferred_start, event.preferred_end) == 3
    check = SafetyCheck.objects.create(
        event=event,
        requested_by=coordinator,
        arrangement_version=arrangement_version(event),
        status=SafetyStatus.APPROVED,
        decided_by=tech,
        decided_at=timezone.now(),
    )
    assert not any(gap.startswith(SAFETY_CHECK_ITEM) for gap in confirmation_gaps(event))
    assert change(api, coordinator, item).status_code == 200
    row = EquipmentReservation.objects.get(request=item)
    assert row.quantity == 3 and row.status == "ACTIVE"
    assert available_quantity(stock, event.preferred_start, event.preferred_end) == 5
    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED
    assert f"{SAFETY_CHECK_ITEM}: no approved check." in confirmation_gaps(event)
    assert not item.plan.technical_approvals.filter(status="APPROVED").exists()


def test_s75_03_withdraw_retains_history_and_releases_once(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item, withdraw=True).status_code == 200
    item.refresh_from_db()
    row = EquipmentReservation.objects.get(request=item)
    assert item.status == "WITHDRAWN" and row.status == "RELEASED"
    assert row.released_by == coordinator and row.released_at is not None
    assert (
        available_quantity(stock, event.preferred_start, event.preferred_end)
        == stock.total_quantity
    )
    assert change(api, coordinator, item, withdraw=True).status_code == 409
    assert EquipmentHistory.objects.filter(request=item, action="WITHDRAWN").count() == 1


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "3", None])
def test_s75_04_invalid_quantity_no_writes(api, event, stock, coordinator, quantity):
    item = request_item(event, stock, coordinator, 5)
    assert change(api, coordinator, item, quantity=quantity).status_code == 400
    item.refresh_from_db()
    assert item.quantity == 5
    assert not EquipmentHistory.objects.filter(action="AMENDED").exists()


@pytest.mark.parametrize("who", ["tech", "second_coordinator", "organiser", "lead", "attendee"])
def test_s75_05_forbidden_actor(api, event, stock, coordinator, who, request):
    actor = request.getfixturevalue(who)
    item = request_item(event, stock, coordinator)
    assert change(api, actor, item).status_code == 403
    assert not EquipmentHistory.objects.filter(action="AMENDED").exists()


def test_s75_06_stale_and_over_capacity_leave_reservation_unchanged(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item, revision=0).status_code == 409
    assert change(api, coordinator, item, quantity=stock.total_quantity + 1).status_code == 409
    assert EquipmentReservation.objects.get(request=item).quantity == 5


@pytest.mark.parametrize("withdraw", [False, True])
def test_s75_07_notification_failure_rolls_back_everything(
    api, event, stock, coordinator, tech, withdraw
):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    revision = EquipmentPlan.objects.get(event=event).revision
    notices = Notification.objects.count()
    histories = EquipmentHistory.objects.count()
    with patch(
        "apps.notifications.models.Notification.objects.bulk_create",
        side_effect=RuntimeError("failed"),
    ):
        with pytest.raises(RuntimeError):
            change(api, coordinator, item, withdraw=withdraw)
    item.refresh_from_db()
    assert item.quantity == 5 and item.status == "RESERVED"
    assert EquipmentReservation.objects.get(request=item).status == "ACTIVE"
    assert EquipmentReservation.objects.get(request=item).quantity == 5
    assert EquipmentPlan.objects.get(event=event).revision == revision
    assert Notification.objects.count() == notices and EquipmentHistory.objects.count() == histories


def test_s75_08_requirements_only_and_noop_do_not_release_stock(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item, quantity=5).status_code == 200
    row = EquipmentReservation.objects.get(request=item)
    assert row.status == "ACTIVE" and row.quantity == 5
    revision = EquipmentPlan.objects.get(event=event).revision
    count = EquipmentHistory.objects.count()
    assert change(api, coordinator, item, quantity=5).status_code == 200
    assert EquipmentPlan.objects.get(event=event).revision == revision
    assert EquipmentHistory.objects.count() == count


@pytest.mark.parametrize("status", ["CONFIRMED", "COMPLETED", "CANCELLED"])
def test_s75_09_closed_or_confirmed_events_refuse_direct_edits(
    api, event, stock, coordinator, status
):
    item = request_item(event, stock, coordinator, 5)
    event.status = status
    event.save()
    assert change(api, coordinator, item).status_code == 409
    assert change(api, coordinator, item, withdraw=True).status_code == 409
    assert not EquipmentHistory.objects.filter(action="AMENDED").exists()


def test_s75_10_increase_requires_technical_rereservation(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item, quantity=7).status_code == 200
    item.refresh_from_db()
    assert item.status == "REQUESTED" and item.quantity == 7
    assert not item.reservations.filter(status="ACTIVE").exists()
    assert (
        reserve_as(api, tech, item, EquipmentPlan.objects.get(event=event).revision).status_code
        == 200
    )
    assert item.reservations.get(status="ACTIVE").quantity == 7


def test_s75_11_other_event_reservation_is_preserved(api, event, stock, coordinator, tech):
    from conftest import make_event

    other = make_event(
        event.created_by,
        status="PLANNING",
        coordinator=coordinator,
        preferred_start=event.preferred_start,
        preferred_end=event.preferred_end,
    )
    first = request_item(event, stock, coordinator, 5)
    second = request_item(other, stock, coordinator, 2)
    assert reserve_as(api, tech, first).status_code == 200
    assert reserve_as(api, tech, second).status_code == 200
    assert change(api, coordinator, first).status_code == 200
    assert available_quantity(stock, event.preferred_start, event.preferred_end) == 5
    assert change(api, coordinator, first, withdraw=True).status_code == 200
    assert available_quantity(stock, event.preferred_start, event.preferred_end) == 8
    assert EquipmentReservation.objects.get(request=second).quantity == 2


@pytest.mark.django_db(transaction=True)
def test_s75_12_parallel_changes_accept_only_one_revision(api, event, stock, coordinator, tech):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from rest_framework.test import APIClient

    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    revision = EquipmentPlan.objects.get(event=event).revision
    barrier = Barrier(2)

    def attempt(withdraw):
        close_old_connections()
        try:
            client = APIClient()
            barrier.wait(timeout=10)
            return change(
                client, coordinator, item, withdraw=withdraw, revision=revision
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [False, True]))
    assert sorted(results) == [200, 409]
    assert EquipmentPlan.objects.get(event=event).revision == revision + 1
    assert (
        EquipmentHistory.objects.filter(request=item, action__in=["AMENDED", "WITHDRAWN"]).count()
        == 1
    )


def test_s75_13_staff_reapproves_retained_reservations(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator, 5)
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item).status_code == 200
    revision = EquipmentPlan.objects.get(event=event).revision
    url = f"/api/events/{event.pk}/approve-revised-equipment/"
    assert api.post(url, {"expected_revision": revision}, format="json").status_code == 403
    api.force_authenticate(tech)
    response = api.post(url, {"expected_revision": revision}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["technical_approval"]["revision"] == revision + 1
    assert EquipmentReservation.objects.get(request=item).quantity == 3
    assert api.post(url, {"expected_revision": revision}, format="json").status_code == 409
    assert api.post(url, {"expected_revision": revision + 1}, format="json").status_code == 409


def test_s75_14_reapproval_refuses_pending_or_lost_stock(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator, 5)
    api.force_authenticate(tech)
    url = f"/api/events/{event.pk}/approve-revised-equipment/"
    assert (
        api.post(url, {"expected_revision": item.plan.revision}, format="json").status_code == 409
    )
    assert reserve_as(api, tech, item).status_code == 200
    assert change(api, coordinator, item).status_code == 200
    stock.total_quantity = 2
    stock.save()
    api.force_authenticate(tech)
    revision = EquipmentPlan.objects.get(event=event).revision
    assert api.post(url, {"expected_revision": revision}, format="json").status_code == 409
    assert not item.plan.technical_approvals.filter(status="APPROVED").exists()


def test_s75_15_unreserved_withdrawal_and_malformed_inputs(api, event, stock, coordinator):
    item = request_item(event, stock, coordinator, 5)
    api.force_authenticate(coordinator)
    assert (
        api.post(f"/api/equipment/requests/{item.pk}/amend/", [], format="json").status_code == 400
    )
    assert change(api, coordinator, item, requirements=17).status_code == 400
    assert change(api, coordinator, item, revision=True).status_code == 400
    assert change(api, coordinator, item, withdraw=True).status_code == 200
    assert change(api, coordinator, item).status_code == 409


def test_s75_16_reapproval_with_no_plan_refuses_cleanly(api, event, tech):
    api.force_authenticate(tech)
    response = api.post(
        f"/api/events/{event.pk}/approve-revised-equipment/",
        {"expected_revision": 0},
        format="json",
    )
    assert response.status_code == 409
    assert not EquipmentPlan.objects.filter(event=event).exists()


def test_s75_17_reassignment_and_elapsed_event_refuse(
    api, event, stock, coordinator, second_coordinator
):
    from apps.equipment.reservations import EquipmentActionDenied
    from apps.equipment.services import amend_request

    item = request_item(event, stock, coordinator, 5)
    event.coordinator = second_coordinator
    event.save()
    with pytest.raises(EquipmentActionDenied):
        amend_request(
            equipment_request=item,
            actor=coordinator,
            expected_revision=item.plan.revision,
            quantity=3,
            technical_requirements="Updated",
        )
    event.preferred_end = timezone.now() - timezone.timedelta(seconds=1)
    event.preferred_start = event.preferred_end - timezone.timedelta(hours=1)
    event.save()
    assert change(api, second_coordinator, item).status_code == 409
