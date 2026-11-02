"""G16b/INT-03: real reserve, manual release and atomic event cancellation."""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentPlan,
    EquipmentReservation,
    TechnicalApproval,
)
from apps.equipment.tests.test_scrum_16_reserve_equipment import event as event
from apps.equipment.tests.test_scrum_16_reserve_equipment import request_item, reserve_as
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import arrangement_version
from apps.venues.tests.test_scrum_11_request_booking import hall as hall
from apps.venues.tests.test_scrum_11_request_booking import request_as
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db


def reserved(api, event, stock, coordinator, tech, quantity=6):
    item = request_item(event, stock, coordinator, quantity)
    response = reserve_as(api, tech, item)
    assert response.status_code == 200, response.data
    return EquipmentReservation.objects.get(request=item)


def release_as(api, tech, row, reason="No longer needed", revision=None):
    api.force_authenticate(tech)
    revision = (
        EquipmentPlan.objects.get(event=row.request.plan.event).revision
        if revision is None
        else revision
    )
    return api.post(
        f"/api/equipment/reservations/{row.pk}/release/",
        {"expected_revision": revision, "reason": reason},
        format="json",
    )


def cancel_as(api, actor, event, **overrides):
    api.force_authenticate(actor)
    preview = api.get(f"/api/events/{event.pk}/cancellation-preview/")
    if preview.status_code != 200:
        return preview
    data = {
        "expected_version": preview.data["version"],
        "confirm_cancel": True,
        "reason": "Client cancelled the event.",
    }
    data.update(overrides)
    return api.post(f"/api/events/{event.pk}/cancel/", data, format="json")


def add_booking(api, coordinator, venue_staff, event, hall, approved=True):
    # Keep the actual equipment and venue periods identical.
    response = request_as(
        api,
        coordinator,
        event,
        hall,
        starts_at=event.preferred_start.isoformat(),
        ends_at=event.preferred_end.isoformat(),
        attendance=60,
    )
    assert response.status_code == 201, response.data
    booking = event.venue_bookings.get()
    if approved:
        api.force_authenticate(venue_staff)
        response = api.post(f"/api/venue-bookings/{booking.pk}/approve/", {}, format="json")
        assert response.status_code == 200, response.data
    return booking


def test_s77_01_ac2_ac3_manual_release_persists_exact_metadata_and_restores_stock(
    api, event, stock, coordinator, tech
):
    row = reserved(api, event, stock, coordinator, tech)
    before = timezone.now()
    response = release_as(api, tech, row, "  Spare equipment returned  ")
    assert response.status_code == 200, response.data
    row.refresh_from_db()
    row.request.refresh_from_db()
    assert row.status == "RELEASED" and row.released_by_id == tech.pk
    assert row.released_at >= before and row.release_reason == "Spare equipment returned"
    assert row.request.status == "REQUESTED"
    assert (
        EquipmentHistory.objects.filter(
            reservation=row, action="RELEASED", actor=tech, reason="Spare equipment returned"
        ).count()
        == 1
    )
    assert not TechnicalApproval.objects.filter(status="APPROVED").exists()
    assert response.data["reservations"][0]["released_by_name"] == tech.email
    assert release_as(api, tech, row).status_code == 409
    assert EquipmentHistory.objects.filter(action="RELEASED").count() == 1
    other = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_start,
        preferred_end=event.preferred_end,
    )
    api.force_authenticate(coordinator)
    assert (
        api.get(f"/api/events/{other.pk}/equipment-availability/").data["equipment"][0][
            "available_quantity"
        ]
        == 10
    )


def test_s77_02_release_then_rereserve_retains_both_records(api, event, stock, coordinator, tech):
    row = reserved(api, event, stock, coordinator, tech)
    assert release_as(api, tech, row).status_code == 200
    item = row.request
    item.plan.refresh_from_db()
    assert reserve_as(api, tech, item, item.plan.revision).status_code == 200
    assert EquipmentReservation.objects.filter(request=item).count() == 2
    assert EquipmentReservation.objects.filter(request=item, status="ACTIVE").count() == 1
    row.refresh_from_db()
    assert row.status == "RELEASED"


@pytest.mark.parametrize("reason", ["", "   ", None, 17])
def test_s77_03_manual_release_requires_reason(api, event, stock, coordinator, tech, reason):
    row = reserved(api, event, stock, coordinator, tech)
    assert release_as(api, tech, row, reason).status_code == 400
    row.refresh_from_db()
    assert row.status == "ACTIVE"


@pytest.mark.parametrize("status", ["PLANNING", "CONFIRMED", "COMPLETED", "CANCELLED"])
def test_s77_04_ac4_elapsed_event_refuses_release_even_with_stale_status(
    api, event, stock, coordinator, tech, status
):
    row = reserved(api, event, stock, coordinator, tech)
    event.status = status
    event.preferred_end = timezone.now() - timezone.timedelta(seconds=1)
    event.save()
    assert release_as(api, tech, row).status_code == 409
    row.refresh_from_db()
    assert row.status == "ACTIVE"


def test_s77_05_ac6_release_supersedes_safety_and_returns_confirmed_to_planning(
    api, event, stock, coordinator, tech
):
    row = reserved(api, event, stock, coordinator, tech)
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
    assert release_as(api, tech, row).status_code == 200
    check.refresh_from_db()
    event.refresh_from_db()
    assert check.status == "SUPERSEDED" and event.status == "PLANNING"


def test_s77_06_manual_release_failure_rolls_back_all_side_effects(
    api, event, stock, coordinator, tech
):
    row = reserved(api, event, stock, coordinator, tech)
    count = EquipmentHistory.objects.count()
    notices = Notification.objects.count()
    with patch(
        "apps.equipment.releases.arrangements_changed", side_effect=RuntimeError("Safety failed")
    ):
        with pytest.raises(RuntimeError):
            release_as(api, tech, row)
    row.refresh_from_db()
    assert row.status == "ACTIVE" and row.released_at is None
    assert EquipmentHistory.objects.count() == count and Notification.objects.count() == notices
    assert TechnicalApproval.objects.filter(status="APPROVED").exists()


@pytest.mark.parametrize("approved", [False, True])
def test_s77_07_ac1_cancel_releases_real_equipment_and_venue_together(
    api, event, stock, coordinator, tech, venue_staff, hall, approved
):
    event.preferred_start = timezone.localtime(event.preferred_start).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    event.preferred_end = event.preferred_start + timezone.timedelta(hours=2)
    event.save()
    row = reserved(api, event, stock, coordinator, tech)
    booking = add_booking(api, coordinator, venue_staff, event, hall, approved)
    response = cancel_as(api, coordinator, event)
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    booking.refresh_from_db()
    row.refresh_from_db()
    assert (
        event.status == "CANCELLED" and booking.status == "WITHDRAWN" and row.status == "RELEASED"
    )
    assert (
        row.release_reason == "Client cancelled the event." and row.released_by_id == coordinator.pk
    )
    assert booking.history.order_by("pk").last().actor_id == coordinator.pk
    assert booking.history.order_by("pk").last().reason == "Client cancelled the event."
    assert event.equipment_plan.requests.get().status == "WITHDRAWN"
    api.force_authenticate(coordinator)
    period = {
        "starts_at": event.preferred_start.isoformat(),
        "ends_at": event.preferred_end.isoformat(),
    }
    assert api.get(f"/api/venues/{hall.pk}/availability/", period).data["conflicts"] == []
    assert (
        api.get(f"/api/events/{event.pk}/equipment-availability/").data["equipment"][0][
            "available_quantity"
        ]
        == 10
    )
    for user in (coordinator, event.created_by, tech, venue_staff):
        assert (
            Notification.objects.filter(event=event, recipient=user, kind="EVENT_CANCELLED").count()
            == 1
        )
    assert EventStatusHistory.objects.filter(event=event, to_status="CANCELLED").count() == 1
    assert cancel_as(api, coordinator, event).status_code == 409
    assert EquipmentHistory.objects.filter(action="RELEASED").count() == 1


def test_s77_08_cancellation_preserves_another_events_reservations(
    api, event, stock, coordinator, tech
):
    reserved(api, event, stock, coordinator, tech, 4)
    other = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_start,
        preferred_end=event.preferred_end,
    )
    other_row = reserved(api, other, stock, coordinator, tech, 3)
    assert cancel_as(api, coordinator, event).status_code == 200
    other_row.refresh_from_db()
    assert other_row.status == "ACTIVE"
    third = make_event(
        event.created_by,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=event.preferred_start,
        preferred_end=event.preferred_end,
    )
    api.force_authenticate(coordinator)
    assert (
        api.get(f"/api/events/{third.pk}/equipment-availability/").data["equipment"][0][
            "available_quantity"
        ]
        == 7
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("confirm_cancel", False),
        ("confirm_cancel", "true"),
        ("reason", ""),
        ("expected_version", "stale"),
    ],
)
def test_s77_09_cancellation_needs_confirmation_reason_and_fresh_summary(
    api, event, stock, coordinator, tech, field, value
):
    row = reserved(api, event, stock, coordinator, tech)
    response = cancel_as(api, coordinator, event, **{field: value})
    assert response.status_code in (400, 409)
    row.refresh_from_db()
    event.refresh_from_db()
    assert row.status == "ACTIVE" and event.status == "PLANNING"


def test_s77_10_real_resource_change_invalidates_preview(api, event, stock, coordinator, tech):
    item = request_item(event, stock, coordinator)
    api.force_authenticate(coordinator)
    old = api.get(f"/api/events/{event.pk}/cancellation-preview/").data["version"]
    assert reserve_as(api, tech, item).status_code == 200
    api.force_authenticate(coordinator)
    response = api.post(
        f"/api/events/{event.pk}/cancel/",
        {"expected_version": old, "confirm_cancel": True, "reason": "Cancelled"},
        format="json",
    )
    assert response.status_code == 409
    assert EquipmentReservation.objects.get().status == "ACTIVE"


@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_ORGANISER,
        Role.TECHNICAL_SUPPORT,
        Role.VENUE_STAFF,
        Role.EVENT_COORDINATOR_LEAD,
        Role.SAFETY_OFFICER,
        Role.ATTENDEE,
    ],
)
def test_s77_11_cancellation_refuses_non_coordinator_roles(api, event, role):
    actor = _make_user(f"cancel-{role}@example.com", role)
    assert cancel_as(api, actor, event).status_code == 403


def test_s77_12_previous_coordinator_cannot_cancel_or_preview(api, event, second_coordinator):
    assert cancel_as(api, second_coordinator, event).status_code == 403
    api.force_authenticate(second_coordinator)
    assert (
        api.post(
            f"/api/events/{event.pk}/cancel/", {"confirm_cancel": True}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.parametrize("stage", ["booking", "equipment", "final_safety", "notices"])
def test_s77_13_cancellation_failure_rolls_back_resources_status_approvals_history_and_notices(
    api, event, stock, coordinator, tech, venue_staff, hall, stage
):
    event.preferred_start = timezone.localtime(event.preferred_start).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    event.preferred_end = event.preferred_start + timezone.timedelta(hours=2)
    event.save()
    row = reserved(api, event, stock, coordinator, tech)
    booking = add_booking(api, coordinator, venue_staff, event, hall)
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
    counts = (
        EquipmentHistory.objects.count(),
        Notification.objects.count(),
        EventStatusHistory.objects.count(),
        booking.history.count(),
    )
    targets = {
        "booking": "apps.events.cancellation.transition_booking",
        "equipment": "apps.events.cancellation.release_for_cancelled_event",
        "final_safety": "apps.events.cancellation.arrangements_changed",
        "notices": "apps.events.cancellation.notify_cancellation",
    }
    with patch(targets[stage], side_effect=RuntimeError("Injected cancellation failure")):
        with pytest.raises(RuntimeError):
            cancel_as(api, coordinator, event)
    event.refresh_from_db()
    row.refresh_from_db()
    booking.refresh_from_db()
    check.refresh_from_db()
    assert (event.status, row.status, booking.status, check.status) == (
        "CONFIRMED",
        "ACTIVE",
        "APPROVED",
        "APPROVED",
    )
    assert counts == (
        EquipmentHistory.objects.count(),
        Notification.objects.count(),
        EventStatusHistory.objects.count(),
        booking.history.count(),
    )
    assert TechnicalApproval.objects.filter(status="APPROVED").exists()


def test_s77_14_cancel_without_resources_or_plan_is_usable(api, event, coordinator):
    response = cancel_as(api, coordinator, event)
    assert response.status_code == 200, response.data
    assert response.data["released_equipment_reservations"] == 0
    event.refresh_from_db()
    assert event.status == "CANCELLED"


@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_COORDINATOR,
        Role.EVENT_ORGANISER,
        Role.VENUE_STAFF,
        Role.EVENT_COORDINATOR_LEAD,
        Role.SAFETY_OFFICER,
        Role.ATTENDEE,
    ],
)
def test_s77_15_release_refuses_non_technical_roles(api, event, stock, coordinator, tech, role):
    row = reserved(api, event, stock, coordinator, tech)
    actor = _make_user(f"release-{role}@example.com", role)
    assert release_as(api, actor, row).status_code == 403
    row.refresh_from_db()
    assert row.status == "ACTIVE"


@pytest.mark.parametrize("status", ["DRAFT", "COMPLETED", "CANCELLED", "REJECTED"])
def test_s77_16_terminal_or_private_event_cannot_be_cancelled(api, event, coordinator, status):
    event.status = status
    event.save()
    assert cancel_as(api, coordinator, event).status_code == 409


def test_s77_17_cancel_pending_equipment_and_explicit_no_equipment_plan(
    api, event, stock, coordinator, tech
):
    item = request_item(event, stock, coordinator)
    assert cancel_as(api, coordinator, event).status_code == 200
    item.refresh_from_db()
    assert item.status == "WITHDRAWN"
    another = make_event(event.created_by, status=EventStatus.PLANNING, coordinator=coordinator)
    api.force_authenticate(tech)
    assert (
        api.post(
            f"/api/events/{another.pk}/approve-no-equipment/",
            {"expected_revision": 0, "acknowledged": True, "notes": "No stock needed"},
            format="json",
        ).status_code
        == 200
    )
    assert cancel_as(api, coordinator, another).status_code == 200
    assert not TechnicalApproval.objects.filter(plan__event=another, status="APPROVED").exists()


def test_s77_18_cancelled_equipment_slice_and_release_primitive_are_idempotent(
    api, event, stock, coordinator, tech
):
    from django.db import transaction

    from apps.equipment.releases import release_for_cancelled_event, release_record

    row = reserved(api, event, stock, coordinator, tech)
    assert cancel_as(api, coordinator, event).status_code == 200
    count = EquipmentHistory.objects.count()
    assert release_for_cancelled_event(event=event, actor=coordinator, reason="Replay") == 0
    row.refresh_from_db()
    with transaction.atomic():
        assert release_record(row, plan=row.request.plan, actor=tech, reason="Replay") is False
    assert EquipmentHistory.objects.count() == count


def test_s77_19_release_slice_requires_cancelled_status_and_current_coordinator(
    api, event, coordinator, tech
):
    from apps.equipment.releases import release_for_cancelled_event
    from apps.equipment.reservations import EquipmentActionDenied, EquipmentActionError

    with pytest.raises(EquipmentActionDenied):
        release_for_cancelled_event(event=event, actor=tech, reason="Attempt")
    with pytest.raises(EquipmentActionError):
        release_for_cancelled_event(event=event, actor=coordinator, reason="Attempt")


def test_s77_20_elapsed_cancel_malformed_and_missing_records_refuse(
    api, event, stock, coordinator, tech
):
    row = reserved(api, event, stock, coordinator, tech)
    assert release_as(api, tech, row, revision=0).status_code == 409
    api.force_authenticate(coordinator)
    assert api.post(f"/api/events/{event.pk}/cancel/", [], format="json").status_code == 400
    assert api.get("/api/events/999999/cancellation-preview/").status_code == 404
    event.preferred_end = timezone.now() - timezone.timedelta(seconds=1)
    event.save()
    assert cancel_as(api, coordinator, event).status_code == 409
    row.refresh_from_db()
    assert row.status == "ACTIVE"


def test_s77_21_cancel_current_safety_check_notifies_officers_without_reopening_planning(
    api, event, stock, coordinator, tech
):
    reserved(api, event, stock, coordinator, tech)
    officer = _make_user("cancel-safety@example.com", Role.SAFETY_OFFICER)
    check = SafetyCheck.objects.create(
        event=event,
        requested_by=coordinator,
        arrangement_version=arrangement_version(event),
        status=SafetyStatus.APPROVED,
        decided_by=officer,
        decided_at=timezone.now(),
    )
    event.status = EventStatus.CONFIRMED
    event.save()
    assert cancel_as(api, coordinator, event).status_code == 200
    check.refresh_from_db()
    assert check.status == "SUPERSEDED"
    assert Notification.objects.filter(recipient=officer, kind="EVENT_CANCELLED").exists()
    assert not Notification.objects.filter(event=event, kind="PLANNING_REOPENED").exists()
    assert not EventStatusHistory.objects.filter(event=event, to_status="PLANNING").exists()
