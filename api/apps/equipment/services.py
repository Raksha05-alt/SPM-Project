"""SCRUM-74 / 75 / 12 / 76 / 16 / 77 - equipment requests, availability and reservations."""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentRequest,
    EquipmentRequestChange,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
)
from apps.events.models import EventRequest
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

# Equipment is arranged once ConnectSphere has agreed to plan the event.
PLANNABLE_EVENT_STATUSES = (EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CONFIRMED)


class EquipmentRefused(Exception):
    """An equipment action that cannot go ahead; ``detail`` says why."""

    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


class NotAllowed(Exception):
    pass


def technical_staff():
    return User.objects.filter(role=Role.TECHNICAL_SUPPORT, is_active=True)


def _who(user) -> str:
    return user.get_full_name() or user.email


# --- availability (SCRUM-12, SCRUM-76) ------------------------------------------


def holding_reservations(equipment_type, start, end, *, exclude_event_id=None):
    """Active reservations overlapping [start, end). Cancelled events never hold anything."""
    held = (
        EquipmentReservation.objects.filter(
            equipment_type=equipment_type,
            released_at__isnull=True,
            start__lt=end,
            end__gt=start,
        )
        .exclude(event__status=EventStatus.CANCELLED)
        .select_related("event")
    )
    if exclude_event_id:
        held = held.exclude(event_id=exclude_event_id)
    return held


def available_quantity(equipment_type, start, end, *, exclude_event_id=None) -> int:
    held = holding_reservations(
        equipment_type, start, end, exclude_event_id=exclude_event_id
    ).aggregate(total=Sum("quantity"))["total"]
    return max(equipment_type.in_service_quantity - (held or 0), 0)


def availability_row(equipment_type, start, end, *, event=None) -> dict:
    """SCRUM-12 AC2-AC5 - quantity available for the period, and any shortfall."""
    held_by_others = (
        holding_reservations(
            equipment_type, start, end, exclude_event_id=event.pk if event else None
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    available = max(equipment_type.in_service_quantity - held_by_others, 0)
    row = {
        "equipment": equipment_type.pk,
        "name": equipment_type.name,
        "category": equipment_type.category,
        "total_quantity": equipment_type.total_quantity,
        "out_of_service_quantity": equipment_type.out_of_service_quantity,
        "out_of_service_reason": equipment_type.out_of_service_reason,
        "expected_return": equipment_type.expected_return,
        "reserved_for_other_events": held_by_others,
        "available_quantity": available,
        "status": "Available" if available else "Unavailable",
    }
    if event is not None:
        requests = event.equipment_requests.filter(equipment_type=equipment_type).exclude(
            status=EquipmentRequestStatus.WITHDRAWN
        )
        requested = sum(r.quantity for r in requests)
        reserved = sum(r.reserved_quantity for r in requests)
        outstanding = max(requested - reserved, 0)
        row.update(
            requested_quantity=requested,
            reserved_for_this_event=reserved,
            shortfall=max(outstanding - available, 0),
        )
        if row["shortfall"]:
            row["status"] = f"Short by {row['shortfall']}"
    return row


def holders(equipment_type, start, end) -> list[dict]:
    """SCRUM-76 AC1 / AC3 - events holding the equipment, limited to planning details."""
    return [
        {
            "event": r.event_id,
            "event_name": r.event.name,
            "event_status": r.event.get_status_display(),
            "start": r.start,
            "end": r.end,
            "quantity": r.quantity,
            "coordinator_name": _who(r.event.coordinator) if r.event.coordinator else None,
        }
        for r in holding_reservations(equipment_type, start, end).select_related(
            "event__coordinator"
        )
    ]


# --- requests (SCRUM-74, SCRUM-75) ----------------------------------------------


def _check_plannable(event: EventRequest, user):
    if event.coordinator_id != user.pk:
        raise NotAllowed
    if event.status not in PLANNABLE_EVENT_STATUSES:
        raise EquipmentRefused(
            "Equipment can be requested once the event is approved; "
            f"it is {event.get_status_display()}."
        )


@transaction.atomic
def create_request(event: EventRequest, user, data: dict) -> EquipmentRequest:
    """SCRUM-74 - record what an event needs and tell Technical Support Staff."""
    _check_plannable(event, user)
    request = EquipmentRequest.objects.create(
        event=event, requested_by=user, updated_by=user, **data
    )
    notify(
        technical_staff(),
        event,
        NotificationKind.EQUIPMENT_REQUESTED,
        f"{_who(user)} requested {request.quantity} x {request.equipment_type.name} for "
        f'"{event.name}".',
    )
    return request


def _locked(request: EquipmentRequest) -> EquipmentRequest:
    return (
        EquipmentRequest.objects.select_for_update()
        .select_related("event", "equipment_type")
        .get(pk=request.pk)
    )


def _release(reservation, user, reason, quantity=None):
    """Release all of a reservation, or ``quantity`` units of it (recorded as its own row)."""
    now = timezone.now()
    if quantity is not None and quantity < reservation.quantity:
        reservation.quantity -= quantity
        reservation.save(update_fields=["quantity"])
        return EquipmentReservation.objects.create(
            request=reservation.request,
            event=reservation.event,
            equipment_type=reservation.equipment_type,
            quantity=quantity,
            start=reservation.start,
            end=reservation.end,
            reserved_by=reservation.reserved_by,
            released_at=now,
            released_by=user,
            release_reason=reason,
        )
    reservation.released_at = now
    reservation.released_by = user
    reservation.release_reason = reason
    reservation.save(update_fields=["released_at", "released_by", "release_reason"])
    return reservation


def _release_surplus(request: EquipmentRequest, user, surplus: int, reason: str) -> None:
    for reservation in request.active_reservations().order_by("-reserved_at", "-pk"):
        taken = min(surplus, reservation.quantity)
        _release(reservation, user, reason, quantity=taken)
        surplus -= taken
        if surplus == 0:
            break


@transaction.atomic
def amend_request(request: EquipmentRequest, user, data: dict) -> EquipmentRequest:
    """SCRUM-75 AC1 / AC2 - change quantity or requirements; surplus units are released."""
    request = _locked(request)
    _check_plannable(request.event, user)
    if request.status == EquipmentRequestStatus.WITHDRAWN:
        raise EquipmentRefused("A withdrawn equipment request cannot be changed.")
    changes = []
    quantity = data.get("quantity", request.quantity)
    if quantity != request.quantity:
        changes.append(f"Quantity changed from {request.quantity} to {quantity}.")
        request.quantity = quantity
    requirements = data.get("technical_requirements", request.technical_requirements)
    if requirements != request.technical_requirements:
        changes.append(
            f'Technical requirements changed from "{request.technical_requirements}" '
            f'to "{requirements}".'
        )
        request.technical_requirements = requirements
    if not changes:
        return request
    reserved = request.reserved_quantity
    if reserved > request.quantity:
        surplus = reserved - request.quantity
        _release_surplus(request, user, surplus, "Quantity reduced")
        changes.append(f"{surplus} reserved unit(s) released.")
        reserved = request.quantity
    request.status = (
        EquipmentRequestStatus.RESERVED
        if reserved and reserved >= request.quantity
        else EquipmentRequestStatus.REQUESTED
    )
    request.updated_by = user
    request.save()
    description = " ".join(changes)
    EquipmentRequestChange.objects.create(request=request, description=description, changed_by=user)
    notify(
        technical_staff(),
        request.event,
        NotificationKind.EQUIPMENT_CHANGED,
        f'{request.equipment_type.name} for "{request.event.name}": {description}',
    )
    return request


@transaction.atomic
def withdraw_request(request: EquipmentRequest, user) -> EquipmentRequest:
    """SCRUM-75 AC3 - withdraw the request and release anything held for it."""
    request = _locked(request)
    if request.event.coordinator_id != user.pk:
        raise NotAllowed
    if request.status == EquipmentRequestStatus.WITHDRAWN:
        raise EquipmentRefused("This equipment request has already been withdrawn.")
    released = request.reserved_quantity
    for reservation in request.active_reservations():
        _release(reservation, user, "Request withdrawn")
    request.status = EquipmentRequestStatus.WITHDRAWN
    request.withdrawn_by = user
    request.withdrawn_at = timezone.now()
    request.updated_by = user
    request.save()
    description = "Request withdrawn."
    if released:
        description += f" {released} reserved unit(s) released."
    EquipmentRequestChange.objects.create(request=request, description=description, changed_by=user)
    notify(
        technical_staff(),
        request.event,
        NotificationKind.EQUIPMENT_CHANGED,
        f'{request.equipment_type.name} for "{request.event.name}": {description}',
    )
    return request


# --- reservations (SCRUM-16, SCRUM-77) ------------------------------------------


@transaction.atomic
def reserve(request: EquipmentRequest, user) -> EquipmentReservation:
    """SCRUM-16 - hold the outstanding quantity for the event's period."""
    request = _locked(request)
    # Serialise reservations of the same equipment so two staff cannot both take the last unit.
    equipment_type = EquipmentType.objects.select_for_update().get(pk=request.equipment_type_id)
    event = request.event
    if request.status == EquipmentRequestStatus.WITHDRAWN:
        raise EquipmentRefused("This equipment request has been withdrawn.")
    if event.status not in PLANNABLE_EVENT_STATUSES:
        raise EquipmentRefused(
            f"Equipment cannot be reserved for an event that is {event.get_status_display()}."
        )
    if not (event.preferred_start and event.preferred_end):
        raise EquipmentRefused("The event has no date and time to reserve equipment for.")
    outstanding = request.quantity - request.reserved_quantity
    if outstanding <= 0:
        raise EquipmentRefused("Everything requested is already reserved.")
    if equipment_type.in_service_quantity == 0:
        reason = equipment_type.out_of_service_reason or "damaged or under maintenance"
        raise EquipmentRefused(
            f"{equipment_type.name} cannot be reserved: all units are out of service ({reason}).",
            available_quantity=0,
        )
    available = available_quantity(equipment_type, event.preferred_start, event.preferred_end)
    if outstanding > available:
        raise EquipmentRefused(
            f"Only {available} x {equipment_type.name} available for this period; "
            f"{outstanding} requested.",
            available_quantity=available,
        )
    reservation = EquipmentReservation.objects.create(
        request=request,
        event=event,
        equipment_type=equipment_type,
        quantity=outstanding,
        start=event.preferred_start,
        end=event.preferred_end,
        reserved_by=user,
    )
    request.status = EquipmentRequestStatus.RESERVED
    request.save(update_fields=["status", "updated_at"])
    notify(
        [event.coordinator],
        event,
        NotificationKind.EQUIPMENT_RESERVED,
        f'{outstanding} x {equipment_type.name} reserved for "{event.name}".',
    )
    return reservation


@transaction.atomic
def release(reservation: EquipmentReservation, user, reason: str) -> EquipmentReservation:
    """SCRUM-77 AC2 / AC4 - Technical Support Staff release a reservation by hand."""
    reservation = (
        EquipmentReservation.objects.select_for_update()
        .select_related("event", "request", "equipment_type")
        .get(pk=reservation.pk)
    )
    reason = (reason or "").strip()
    if not reason:
        raise EquipmentRefused("Enter a reason for releasing this reservation.", status=400)
    if reservation.released_at:
        raise EquipmentRefused("This reservation has already been released.")
    event = reservation.event
    if event.status == EventStatus.COMPLETED or reservation.end <= timezone.now():
        raise EquipmentRefused("The event has already taken place; its reservations are kept.")
    _release(reservation, user, reason)
    request = reservation.request
    if request.status == EquipmentRequestStatus.RESERVED:
        request.status = EquipmentRequestStatus.REQUESTED
        request.save(update_fields=["status", "updated_at"])
    notify(
        [event.coordinator],
        event,
        NotificationKind.EQUIPMENT_RELEASED,
        f'{reservation.quantity} x {reservation.equipment_type.name} for "{event.name}" '
        f"was released. Reason: {reason}",
    )
    return reservation


def release_for_cancelled_event(event: EventRequest, user) -> None:
    """SCRUM-77 AC1 - a cancelled event stops holding equipment (cancellation hook)."""
    for reservation in event.equipment_reservations.filter(released_at__isnull=True):
        _release(reservation, user, "Event cancelled")
