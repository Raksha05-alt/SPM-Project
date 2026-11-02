"""SCRUM-16: locked reservations and revision-bound technical approval.

Resource writers lock event, equipment types in ID order, then plan/request/
reservation rows. G17 amendments must use the same order and invalidate the
technical approval with ``advance_plan`` before changing the plan.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types, validate_period
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentReservation,
    ReservationStatus,
    TechnicalApproval,
    TechnicalApprovalStatus,
)
from apps.equipment.services import available_quantity
from apps.events.models import EventRequest
from apps.notifications.models import Notification, NotificationKind
from apps.safety.services import arrangements_changed

OPEN_STATUSES = frozenset({EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CONFIRMED})


class EquipmentActionError(Exception):
    def __init__(self, detail, *, status=409, **fields):
        self.detail, self.status, self.fields = detail, status, fields
        super().__init__(detail)


class EquipmentActionDenied(Exception):
    pass


def require_technical_staff(actor):
    if not User.objects.filter(pk=actor.pk, role=Role.TECHNICAL_SUPPORT, is_active=True).exists():
        raise EquipmentActionDenied("Only active Technical Support staff can change reservations.")


def require_open_event(event):
    if event.status not in OPEN_STATUSES:
        raise EquipmentActionError("This event is closed to equipment changes.")
    if event.preferred_start is None or event.preferred_end is None:
        raise EquipmentActionError("The event needs a start and end before equipment is reserved.")
    from django.core.exceptions import ValidationError

    try:
        validate_period(event.preferred_start, event.preferred_end)
    except ValidationError as exc:
        raise EquipmentActionError(" ".join(exc.messages)) from None
    if event.preferred_end <= timezone.now():
        raise EquipmentActionError("Equipment cannot be changed after the event has taken place.")


def check_revision(plan, expected_revision):
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise EquipmentActionError("Supply the equipment plan revision.", status=400)
    if plan.revision != expected_revision:
        raise EquipmentActionError("The equipment plan changed. Reload it before continuing.")


def advance_plan(plan, actor, reason):
    """Caller holds the event lock. Preserve approvals as superseded evidence."""
    approvals = plan.technical_approvals.filter(status=TechnicalApprovalStatus.APPROVED)
    for approval in approvals:
        approval.status = TechnicalApprovalStatus.SUPERSEDED
        approval.superseded_at = timezone.now()
        approval.save(update_fields=["status", "superseded_at", "updated_at"])
        EquipmentHistory.objects.create(
            plan=plan,
            action=EquipmentHistoryAction.SUPERSEDED,
            plan_revision=plan.revision,
            before={"approval": approval.pk, "revision": approval.plan_revision},
            reason=reason,
            actor=actor,
        )
    plan.revision += 1
    plan.save(update_fields=["revision", "updated_at"])


def notify_coordinator(event, message):
    if event.coordinator_id:
        Notification.objects.create(
            recipient_id=event.coordinator_id,
            event=event,
            kind=NotificationKind.EQUIPMENT_UPDATED,
            message=message,
        )


def approve_plan(plan, actor, *, no_equipment=False, notes=""):
    approval = TechnicalApproval.objects.create(
        plan=plan,
        plan_revision=plan.revision,
        no_equipment_required=no_equipment,
        notes=notes,
        approved_by=actor,
    )
    EquipmentHistory.objects.create(
        plan=plan,
        action=EquipmentHistoryAction.APPROVED,
        plan_revision=plan.revision,
        after={"approval": approval.pk, "no_equipment_required": no_equipment},
        actor=actor,
    )
    return approval


def _fully_reserved(plan, event):
    for item in plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN):
        if item.status != EquipmentRequestStatus.RESERVED:
            return False
        if not item.reservations.filter(
            status=ReservationStatus.ACTIVE,
            quantity=item.quantity,
            starts_at=event.preferred_start,
            ends_at=event.preferred_end,
        ).exists():
            return False
    return True


@transaction.atomic
def reserve(*, equipment_request, actor, expected_revision):
    require_technical_staff(actor)
    event_id = equipment_request.plan.event_id
    event = EventRequest.objects.select_for_update().get(pk=event_id)
    require_open_event(event)
    [stock] = lock_equipment_types([equipment_request.equipment_type_id])
    plan = EquipmentPlan.objects.select_for_update().get(event=event)
    check_revision(plan, expected_revision)
    item = EquipmentRequest.objects.select_for_update().get(pk=equipment_request.pk)
    if (
        item.status != EquipmentRequestStatus.REQUESTED
        or item.reservations.filter(status=ReservationStatus.ACTIVE).exists()
    ):
        raise EquipmentActionError("This request is no longer awaiting a reservation. Reload it.")
    available = available_quantity(stock, event.preferred_start, event.preferred_end)
    if item.quantity > available:
        raise EquipmentActionError(
            f"Cannot reserve {item.quantity} x {stock.name}: {available} available for this period.",
            available_quantity=available,
            requested_quantity=item.quantity,
        )
    advance_plan(plan, actor, "Equipment reserved.")
    reservation = EquipmentReservation.objects.create(
        request=item,
        quantity=item.quantity,
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
        reserved_by=actor,
    )
    item.status = EquipmentRequestStatus.RESERVED
    item.save(update_fields=["status", "updated_at"])
    EquipmentHistory.objects.create(
        plan=plan,
        request=item,
        reservation=reservation,
        action=EquipmentHistoryAction.RESERVED,
        plan_revision=plan.revision,
        after={
            "reservation": reservation.pk,
            "quantity": reservation.quantity,
            "starts_at": reservation.starts_at.isoformat(),
            "ends_at": reservation.ends_at.isoformat(),
        },
        actor=actor,
    )
    if _fully_reserved(plan, event):
        approve_plan(plan, actor)
    arrangements_changed(event, f"{item.quantity} x {stock.name} reserved.", actor)
    notify_coordinator(event, f'{item.quantity} x {stock.name} reserved for "{event.name}".')
    return reservation


@transaction.atomic
def approve_no_equipment(*, event, actor, expected_revision, acknowledged=False, notes=""):
    require_technical_staff(actor)
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    require_open_event(event)
    if acknowledged is not True or not isinstance(notes, str) or not notes.strip():
        raise EquipmentActionError(
            "Confirm that no equipment is needed and record the technical review notes.", status=400
        )
    plan, _ = EquipmentPlan.objects.select_for_update().get_or_create(event=event)
    check_revision(plan, expected_revision)
    if plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN).exists():
        raise EquipmentActionError("The plan has equipment requests; reserve them instead.")
    if plan.technical_approvals.filter(status=TechnicalApprovalStatus.APPROVED).exists():
        raise EquipmentActionError("This plan already has a technical approval.")
    advance_plan(plan, actor, "Technical Support reviewed a plan requiring no equipment.")
    approval = approve_plan(plan, actor, no_equipment=True, notes=notes.strip())
    arrangements_changed(event, "Technical arrangements approved without equipment.", actor)
    notify_coordinator(
        event, f'Technical Support confirmed no equipment is needed for "{event.name}".'
    )
    return approval
