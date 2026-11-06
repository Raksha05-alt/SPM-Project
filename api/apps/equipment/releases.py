"""SCRUM-77: releases retain history and share the G16 stock/plan locks."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentRequestStatus,
    EquipmentReservation,
    ReservationStatus,
)
from apps.equipment.reservations import (
    EquipmentActionDenied,
    EquipmentActionError,
    advance_plan,
    check_revision,
    notify_coordinator,
    require_open_event,
    require_technical_staff,
)
from apps.events.models import EventRequest
from apps.safety.services import arrangements_changed


def release_reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        raise EquipmentActionError("Enter a reason for releasing the equipment.", status=400)
    return reason.strip()


def release_record(reservation, *, plan, actor, reason):
    """Caller holds event, stock and reservation locks and has advanced the plan.

    G17 can use this for a withdrawn reservation after applying its own actor,
    revision and status checks. A replay returns False and cannot free stock twice.
    """
    if reservation.status != ReservationStatus.ACTIVE:
        return False
    before = {"status": reservation.status, "quantity": reservation.quantity}
    reservation.status = ReservationStatus.RELEASED
    reservation.released_by = actor
    reservation.released_at = timezone.now()
    reservation.release_reason = reason
    reservation.save(
        update_fields=["status", "released_by", "released_at", "release_reason", "updated_at"]
    )
    EquipmentHistory.objects.create(
        plan=plan,
        request=reservation.request,
        reservation=reservation,
        action=EquipmentHistoryAction.RELEASED,
        plan_revision=plan.revision,
        before=before,
        after={"status": reservation.status, "quantity": reservation.quantity},
        reason=reason,
        actor=actor,
    )
    return True


@transaction.atomic
def release(*, reservation, actor, expected_revision, reason):
    require_technical_staff(actor)
    event = EventRequest.objects.select_for_update().get(pk=reservation.request.plan.event_id)
    require_open_event(event)
    lock_equipment_types([reservation.request.equipment_type_id])
    plan = EquipmentPlan.objects.select_for_update().get(event=event)
    check_revision(plan, expected_revision)
    locked = EquipmentReservation.objects.select_for_update().get(pk=reservation.pk)
    reason = release_reason(reason)
    if locked.status != ReservationStatus.ACTIVE:
        raise EquipmentActionError("This reservation has already been released. Reload the plan.")
    advance_plan(plan, actor, reason)
    release_record(locked, plan=plan, actor=actor, reason=reason)
    item = locked.request
    item.status = EquipmentRequestStatus.REQUESTED
    item.save(update_fields=["status", "updated_at"])
    arrangements_changed(event, f"Equipment released: {reason}", actor)
    notify_coordinator(
        event,
        f'{locked.quantity} x {item.equipment_type.name} released for "{event.name}": {reason}',
    )
    return locked


@transaction.atomic
def release_for_cancelled_event(*, event, actor, reason):
    """Cancellation's idempotent equipment slice, inside the outer transaction."""
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if actor.role != Role.EVENT_COORDINATOR or event.coordinator_id != actor.pk:
        raise EquipmentActionDenied("Only the assigned coordinator can cancel this event.")
    if event.status != EventStatus.CANCELLED:
        raise EquipmentActionError(
            "Cancel the event in the resource transaction before releasing it."
        )
    reason = release_reason(reason)
    plan = EquipmentPlan.objects.filter(event=event).first()
    if plan is None:
        return 0
    items = list(plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN).order_by("pk"))
    lock_equipment_types(plan.requests.values_list("equipment_type_id", flat=True))
    plan = EquipmentPlan.objects.select_for_update().get(pk=plan.pk)
    reservations = list(
        EquipmentReservation.objects.select_for_update()
        .filter(request__plan=plan, status=ReservationStatus.ACTIVE)
        .order_by("pk")
    )
    if (
        not items
        and not reservations
        and not plan.technical_approvals.filter(status="APPROVED").exists()
    ):
        return 0
    advance_plan(plan, actor, reason)
    for reservation in reservations:
        release_record(reservation, plan=plan, actor=actor, reason=reason)
    for item in items:
        before = {"status": item.status, "quantity": item.quantity}
        item.status = EquipmentRequestStatus.WITHDRAWN
        item.save(update_fields=["status", "updated_at"])
        EquipmentHistory.objects.create(
            plan=plan,
            request=item,
            action=EquipmentHistoryAction.WITHDRAWN,
            plan_revision=plan.revision,
            before=before,
            after={"status": item.status, "quantity": item.quantity},
            reason=reason,
            actor=actor,
        )
    arrangements_changed(event, f"Event cancelled; equipment released: {reason}", actor)
    return len(reservations)
