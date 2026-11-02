"""SCRUM-74 - the assigned coordinator records the equipment an event requires.

Sprint 3 gate G14. Reservation (SCRUM-16), release (SCRUM-77) and amendment or
withdrawal (SCRUM-75) are separate actions owned by later gates; this module
only creates requests.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types, validate_quantity
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
)

# Equipment is planned once the event is approved, as venues are (SCRUM-11).
EVENT_STATUSES_OPEN_TO_REQUESTS = frozenset({EventStatus.APPROVED, EventStatus.PLANNING})


class NotAssignedToEvent(Exception):
    """AC5 - only the event's assigned coordinator may add an equipment request."""


class EquipmentRequestError(Exception):
    """AC2 and the guide's refusals - every problem by field; nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))


def _clean(equipment_type, quantity, technical_requirements) -> dict:
    errors = {}
    if equipment_type in (None, ""):
        errors["equipment_type"] = "Choose the equipment type."
    elif isinstance(equipment_type, bool) or not isinstance(equipment_type, int):
        errors["equipment_type"] = "Choose an equipment type from the catalogue."
    if quantity in (None, ""):
        errors["quantity"] = "Enter the quantity required."
    else:
        try:
            validate_quantity(quantity)
        except DjangoValidationError:
            # AC2 - zero, negative and non-whole quantities are refused.
            errors["quantity"] = "The quantity must be a whole number of 1 or more."
    if technical_requirements is None:
        technical_requirements = ""
    if not isinstance(technical_requirements, str):
        errors["technical_requirements"] = "Technical requirements must be text."
    if errors:
        raise EquipmentRequestError(errors)
    return {
        "equipment_type": equipment_type,
        "quantity": quantity,
        "technical_requirements": technical_requirements.strip(),
    }


def _snapshot(request: EquipmentRequest) -> dict:
    return {
        "equipment_type": request.equipment_type_id,
        "quantity": request.quantity,
        "technical_requirements": request.technical_requirements,
        "status": request.status,
    }


@transaction.atomic
def create_request(
    *, event, requested_by, equipment_type=None, quantity=None, technical_requirements=""
) -> EquipmentRequest:
    """SCRUM-74 - save one equipment request for ``event``.

    Locks the event, then the equipment type (the shared lock order). Refuses,
    with nothing saved, when the user is not the assigned coordinator (AC5), the
    event is not Approved or Planning, the type is unknown, retired or already
    requested, or the quantity is not a positive whole number (AC2). On success
    it saves the request with who and when (AC4) and a history row, moves an
    Approved event to Planning, marks the equipment plan as changed so an
    earlier technical approval or Safety check no longer covers it, and
    notifies Technical Support (AC4).
    """
    from apps.accounts.models import Role, User
    from apps.events.models import EventRequest
    from apps.events.services import transition_event
    from apps.notifications.models import Notification, NotificationKind
    from apps.safety.services import arrangements_changed

    locked_event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked_event.coordinator_id is None or locked_event.coordinator_id != requested_by.pk:
        raise NotAssignedToEvent
    if locked_event.status not in EVENT_STATUSES_OPEN_TO_REQUESTS:
        raise EquipmentRequestError(
            {
                "event": (
                    "Equipment can be requested once the event is approved; "
                    f"this event is {locked_event.get_status_display()}."
                )
            }
        )
    cleaned = _clean(equipment_type, quantity, technical_requirements)
    try:
        [item] = lock_equipment_types([cleaned["equipment_type"]])
    except DjangoValidationError:
        raise EquipmentRequestError(
            {"equipment_type": "That equipment type is not in the catalogue."}
        ) from None
    if not item.in_service:
        raise EquipmentRequestError(
            {"equipment_type": f"{item.name} is no longer offered for events."}
        )

    plan, _ = EquipmentPlan.objects.select_for_update().get_or_create(event=locked_event)
    if (
        plan.requests.filter(equipment_type=item)
        .exclude(status=EquipmentRequestStatus.WITHDRAWN)
        .exists()
    ):
        raise EquipmentRequestError(
            {
                "equipment_type": (
                    f"{item.name} is already requested for this event. Change that request instead."
                )
            }
        )

    if locked_event.status == EventStatus.APPROVED:
        transition_event(locked_event, EventStatus.PLANNING, requested_by)

    # A new line changes the equipment plan: an approval of the old revision
    # no longer covers it (apps.safety.services._current_technical_approval).
    plan.revision += 1
    plan.save(update_fields=["revision", "updated_at"])
    request = EquipmentRequest.objects.create(
        plan=plan,
        equipment_type=item,
        quantity=cleaned["quantity"],
        technical_requirements=cleaned["technical_requirements"],
        requested_by=requested_by,
    )
    EquipmentHistory.objects.create(
        plan=plan,
        request=request,
        action=EquipmentHistoryAction.REQUESTED,
        plan_revision=plan.revision,
        after=_snapshot(request),
        actor=requested_by,
    )
    # INT-04 - the arrangement version includes open equipment requests.
    arrangements_changed(
        locked_event,
        f"{request.quantity} x {item.name} was requested.",
        requested_by,
    )

    staff = User.objects.filter(role=Role.TECHNICAL_SUPPORT, is_active=True)
    name = requested_by.get_full_name() or requested_by.email
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=member,
                event=locked_event,
                kind=NotificationKind.EQUIPMENT_REQUESTED,
                message=(
                    f'{name} requested {request.quantity} x {item.name} for "{locked_event.name}". '
                    "Review it in Equipment."
                ),
            )
            for member in staff
        ]
    )
    return request


# --------------------------------------------------------------------------
# SCRUM-12 - equipment availability for an event period (Sprint 3 gate G15)
# --------------------------------------------------------------------------
#
# Usable stock is total stock minus active damaged/maintenance records.
# Available for a period is usable stock minus active reservations of other,
# non-cancelled events that overlap it, using half-open [start, end) periods:
# a reservation ending exactly when the period starts does not reduce it.
# Equipment uses the event's actual period; venue setup/turnaround buffers do
# not apply (Sprint 4, SCRUM-85).
#
# The SCRUM-16 reservation action (G16a) should lock the equipment-type rows
# (contracts.lock_equipment_types) and then call ``available_quantity`` to
# refuse over-allocation, so the check and the write see the same stock.


class AvailabilityStatus:
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


def _active_unavailability(equipment_type):
    return equipment_type.unavailability_records.filter(restored_at__isnull=True).order_by(
        "created_at", "pk"
    )


def reserved_quantity(equipment_type, starts_at, ends_at, *, exclude_event=None) -> int:
    """Quantity held by active reservations overlapping ``[starts_at, ends_at)``.

    Reservations of cancelled events and released reservations never count
    (``ReservationQuerySet.active``). ``exclude_event`` leaves out that event's
    own reservations, so an event's equipment is not unavailable to itself.
    """
    from django.db.models import Sum

    from apps.equipment.models import EquipmentReservation

    reservations = (
        EquipmentReservation.objects.active()
        .overlapping(starts_at, ends_at)
        .filter(request__equipment_type=equipment_type)
    )
    if exclude_event is not None:
        reservations = reservations.exclude(request__plan__event=exclude_event)
    return reservations.aggregate(total=Sum("quantity"))["total"] or 0


def available_quantity(equipment_type, starts_at, ends_at, *, exclude_event=None) -> int:
    """SCRUM-12 AC2 - how many units can still be promised for the period.

    Usable stock (total minus damaged or under maintenance) minus overlapping
    reservations for other events, never below zero. A type that is no longer
    offered has none available.
    """
    from apps.equipment.contracts import validate_period

    validate_period(starts_at, ends_at)
    if not equipment_type.in_service:
        return 0
    usable = equipment_type.total_quantity - equipment_type.unavailable_quantity
    reserved = reserved_quantity(equipment_type, starts_at, ends_at, exclude_event=exclude_event)
    return max(0, usable - reserved)


def availability_row(equipment_type, starts_at, ends_at, *, requested=None, event=None) -> dict:
    """SCRUM-12 AC2-AC5 - one equipment type's availability for the period.

    Reports the available quantity, what is unavailable regardless of the
    period (with its reason and expected return when recorded), how much other
    events have reserved (quantities only: SCRUM-76 shows which events), and
    the shortfall against ``requested``.
    """
    from apps.equipment.contracts import validate_period

    validate_period(starts_at, ends_at)
    records = list(_active_unavailability(equipment_type))
    unavailable = sum(r.quantity for r in records)
    reserved_elsewhere = reserved_quantity(equipment_type, starts_at, ends_at, exclude_event=event)
    reserved_here = (
        reserved_quantity(equipment_type, starts_at, ends_at) - reserved_elsewhere
        if event is not None
        else 0
    )
    available = available_quantity(equipment_type, starts_at, ends_at, exclude_event=event)
    shortfall = max(0, requested - available) if requested is not None else 0
    if available == 0:
        status = AvailabilityStatus.UNAVAILABLE
    elif shortfall or available < equipment_type.total_quantity:
        status = AvailabilityStatus.PARTIAL
    else:
        status = AvailabilityStatus.AVAILABLE
    return {
        "equipment_type": equipment_type.pk,
        "code": equipment_type.code,
        "name": equipment_type.name,
        "in_service": equipment_type.in_service,
        "total_quantity": equipment_type.total_quantity,
        "unavailable_quantity": unavailable,
        "unavailable": [
            {
                "quantity": r.quantity,
                "cause": r.cause,
                "cause_label": r.get_cause_display(),
                "reason": r.reason,
                "expected_return_at": r.expected_return_at,
            }
            for r in records
        ],
        "reserved_for_other_events": reserved_elsewhere,
        "reserved_for_this_event": reserved_here,
        "available_quantity": available,
        "requested_quantity": requested,
        "shortfall": shortfall,
        "status": status,
    }


# --------------------------------------------------------------------------
# SCRUM-76 - which events are holding the equipment (Sprint 3 gate G18)
# --------------------------------------------------------------------------
#
# The holders are exactly the reservations SCRUM-12 subtracts: active
# reservations, of events that are not cancelled, overlapping the period
# (half-open). A cancelled event's reservations are released by the
# cancellation action (SCRUM-77 / INT-03) and, even before that, never count,
# so the next availability check shows the equipment as available again (AC4).


def holding_reservations(equipment_type, starts_at, ends_at, *, exclude_event=None):
    """Active reservations of other, non-cancelled events holding ``equipment_type``
    during ``[starts_at, ends_at)``, earliest first."""
    from apps.equipment.contracts import validate_period
    from apps.equipment.models import EquipmentReservation

    validate_period(starts_at, ends_at)
    reservations = (
        EquipmentReservation.objects.active()
        .overlapping(starts_at, ends_at)
        .filter(request__equipment_type=equipment_type)
        .select_related("request__plan__event__coordinator")
        .order_by("starts_at", "pk")
    )
    if exclude_event is not None:
        reservations = reservations.exclude(request__plan__event=exclude_event)
    return list(reservations)


def _person(user):
    if user is None:
        return None
    return {"name": user.get_full_name() or user.email, "email": user.email}


def holders(equipment_type, starts_at, ends_at, *, viewer, event=None) -> list[dict]:
    """SCRUM-76 AC1/AC3 - the events holding the equipment, scoped to ``viewer``.

    Technical Support, who negotiate for the equipment, see each holding event's
    name, status and coordinator contact with the reserved quantity and period.
    The requesting event's coordinator sees only the quantity and period held
    elsewhere: another client's event is not theirs to see (US-01.2). Nobody is
    shown the holding event's organisation or client details.
    """
    from apps.accounts.models import Role

    entries = []
    for reservation in holding_reservations(
        equipment_type, starts_at, ends_at, exclude_event=event
    ):
        entry = {
            "reservation": reservation.pk,
            "quantity": reservation.quantity,
            "starts_at": reservation.starts_at,
            "ends_at": reservation.ends_at,
        }
        if viewer.role == Role.TECHNICAL_SUPPORT:
            held_by = reservation.request.plan.event
            entry["event"] = {
                "id": held_by.pk,
                "name": held_by.name,
                "status": held_by.status,
                "status_label": held_by.get_status_display(),
                "coordinator": _person(held_by.coordinator),
            }
        entries.append(entry)
    return entries
