"""SCRUM-58 - Confirm an event after its essential arrangements are complete.

* ``arrangement_gaps`` / ``confirmation_gaps`` (SCRUM-90, ``apps.safety.services``)
  name what is still missing. They are re-exported here so the confirmation
  contract reads in one place.
* ``readiness(event)`` - what the coordinator's Readiness panel shows: each
  essential arrangement, the missing items and any recorded unavailable outcome.
* ``confirm_event(event, actor)`` - the assigned coordinator confirms a Planning
  event. Rereads everything under the agreed locks, refuses with every missing
  item, then records Confirmed, the coordinator and the time, and tells the
  Event Organiser.
* ``confirmed_arrangements(event)`` - what the organiser sees once confirmed.
* ``notify_unavailable(...)`` - AC3: staff record that a venue or technical
  resource is unavailable; the organiser receives the reason.

Lock order (Sprint 3 guide): event row, venue rows in ID order, equipment-type
rows in ID order, then booking and reservation rows.
"""

from django.db import models, transaction
from django.utils import timezone

from apps.core.audit import record
from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentReservation,
    ReservationStatus,
    TechnicalApproval,
    TechnicalApprovalStatus,
)
from apps.events.models import EventRequest
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify, status_occurrence
from apps.safety.models import SafetyStatus
from apps.safety.services import (
    ConfirmationBlocked,
    _active_reservation,
    _approved_bookings,
    _current_technical_approval,
    _equipment_plan,
    _open_equipment_requests,
    arrangement_gaps,
    confirmation_gaps,
    current_check,
    is_stale,
)
from apps.venues.models import BookingStatus, Venue, VenueBooking

__all__ = [
    "ConfirmationBlocked",
    "ConfirmationRefused",
    "arrangement_gaps",
    "confirm_event",
    "confirmation_gaps",
    "confirmed_arrangements",
    "notify_unavailable",
    "readiness",
]


class ConfirmationRefused(Exception):
    """The event is not in a state that can be confirmed (not a missing arrangement)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _name(user):
    return (user.get_full_name() or user.email) if user else None


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


# --------------------------------------------------------------------------
# Reading readiness
# --------------------------------------------------------------------------


def unavailable_outcomes(event: EventRequest) -> list[str]:
    """AC3 - staff decisions that an essential resource cannot be provided.

    A rejected venue booking counts while the event has no approved or pending
    venue; an equipment request counts while it is still unreserved.
    """
    outcomes = []
    bookings = list(event.venue_bookings.select_related("venue").order_by("pk"))
    if not any(b.status in (BookingStatus.APPROVED, BookingStatus.PENDING) for b in bookings):
        for booking in bookings:
            if booking.status == BookingStatus.REJECTED:
                outcomes.append(
                    f"Venue: Venue Staff rejected {booking.venue.name}: {booking.decision_reason}"
                )
    for item in _open_equipment_requests(_equipment_plan(event)):
        if item.status == EquipmentRequestStatus.RESERVED:
            continue
        latest = item.history.order_by("-created_at", "-pk").first()
        if latest is not None and latest.action == EquipmentHistoryAction.UNAVAILABLE:
            outcomes.append(
                f"Equipment: Technical Support recorded {item.quantity} x "
                f"{item.equipment_type.name} as unavailable: {latest.reason}"
            )
    return outcomes


def _safety_item(event: EventRequest) -> dict:
    check = current_check(event)
    if check is None:
        return {"ready": False, "detail": "No approved safety check."}
    if check.status == SafetyStatus.PENDING:
        return {"ready": False, "detail": "Awaiting a Safety Officer."}
    if is_stale(check, event):
        return {"ready": False, "detail": "The arrangements changed after approval."}
    return {
        "ready": True,
        "detail": f"Approved by {_name(check.decided_by)} on {_when(check.decided_at)}.",
    }


def readiness(event: EventRequest) -> dict:
    """AC1/AC2 - each essential arrangement, what is missing and whether to confirm."""
    approved = _approved_bookings(event)
    plan = _equipment_plan(event)
    approval = _current_technical_approval(plan)
    equipment = []
    for item in _open_equipment_requests(plan):
        reservation = _active_reservation(item)
        equipment.append(
            {
                "label": f"{item.quantity} x {item.equipment_type.name}",
                "ready": item.status == EquipmentRequestStatus.RESERVED and reservation is not None,
                "detail": "Reserved" if reservation else item.get_status_display(),
            }
        )
    items = [
        {
            "area": "Venue",
            "label": ", ".join(b.venue.name for b in approved) or "No approved venue",
            "ready": bool(approved)
            and not any(gap.startswith("Venue:") for gap in arrangement_gaps(event)),
            "detail": "Approved by Venue Staff" if approved else "Awaiting an approved booking.",
        },
        {
            "area": "Technical",
            "label": "Equipment plan",
            "ready": approval is not None,
            "detail": (
                f"Approved by {_name(approval.approved_by)}"
                if approval
                else "Awaiting Technical Support approval."
            ),
        },
        *({"area": "Equipment", **row} for row in equipment),
        {"area": "Safety", "label": "Operational safety check", **_safety_item(event)},
    ]
    missing = confirmation_gaps(event)
    return {
        "event": event.pk,
        "status": event.status,
        "items": items,
        "missing": missing,
        "unavailable": unavailable_outcomes(event),
        "can_confirm": event.status == EventStatus.PLANNING and not missing,
        "confirmed_by_name": _name(event.confirmed_by),
        "confirmed_at": event.confirmed_at,
    }


def confirmed_venues(event: EventRequest) -> list[dict]:
    """Public session/venue projection; never includes staff notes or Safety facts."""
    from apps.venues.layouts import label_map

    labels = label_map()
    return [
        {
            "session": b.session_id,
            "session_name": b.session.name,
            "session_kind": b.session.kind,
            "venue": b.venue.name,
            "location": b.venue.location,
            "starts_at": b.starts_at,
            "ends_at": b.ends_at,
            "attendance": b.effective_attendance,
            "layout": labels.get(b.layout, b.layout) if b.layout else "",
        }
        for b in _approved_bookings(event)
    ]


def confirmed_arrangements(event: EventRequest) -> dict:
    """AC5 - the confirmed plan the Event Organiser can rely on.

    Venue, timing, layout and reserved equipment only; staff notes and other
    events' details are left out.
    """
    check = current_check(event)
    return {
        "event": event.pk,
        "status": event.status,
        "confirmed_by_name": _name(event.confirmed_by),
        "confirmed_at": event.confirmed_at,
        "venues": confirmed_venues(event),
        "equipment": [
            {"equipment": item.equipment_type.name, "quantity": reservation.quantity}
            for item in _open_equipment_requests(_equipment_plan(event))
            if (reservation := _active_reservation(item)) is not None
        ],
        "safety_approved_at": (
            check.decided_at if check and check.status == SafetyStatus.APPROVED else None
        ),
    }


# --------------------------------------------------------------------------
# Confirming
# --------------------------------------------------------------------------


def _lock_resources(event: EventRequest) -> None:
    """Lock venues, equipment types, then bookings and reservations, in the shared order."""
    bookings = VenueBooking.objects.filter(
        event=event, status__in=[BookingStatus.PENDING, BookingStatus.APPROVED]
    )
    venue_ids = sorted(set(bookings.values_list("venue_id", flat=True)))
    list(Venue.objects.select_for_update().filter(pk__in=venue_ids).order_by("pk"))
    type_ids = (
        EquipmentRequest.objects.filter(plan__event=event)
        .exclude(status=EquipmentRequestStatus.WITHDRAWN)
        .values_list("equipment_type_id", flat=True)
    )
    lock_equipment_types(type_ids)
    list(bookings.select_for_update().order_by("pk"))
    list(
        EquipmentReservation.objects.select_for_update()
        .filter(request__plan__event=event, status=ReservationStatus.ACTIVE)
        .order_by("pk")
    )


def _arrangement_summary(event: EventRequest) -> str:
    venues = ", ".join(
        f"{b.venue.name} ({_when(b.starts_at)} to {_when(b.ends_at)})"
        for b in _approved_bookings(event)
    )
    equipment = ", ".join(
        f"{r.quantity} x {item.equipment_type.name}"
        for item in _open_equipment_requests(_equipment_plan(event))
        if (r := _active_reservation(item)) is not None
    )
    return f"Venue: {venues}." + (f" Equipment: {equipment}." if equipment else "")


@transaction.atomic
def confirm_event(event: EventRequest, actor) -> EventRequest:
    """AC1/AC2/AC4/AC5 - the assigned coordinator confirms a Planning event.

    Raises NotAssignedCoordinator for anyone but the current assigned
    coordinator, ConfirmationRefused when the event is not in Planning, and
    ConfirmationBlocked listing every missing item. Nothing is saved then.
    """
    from apps.events.services import NotAssignedCoordinator, transition_event

    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    # Reread the assignment under the lock (SCRUM-89 ownership contract).
    if not (actor.is_coordinator and actor.is_active) or locked.coordinator_id != actor.pk:
        raise NotAssignedCoordinator
    if locked.status == EventStatus.CONFIRMED:
        raise ConfirmationRefused("This event is already confirmed.")
    if locked.status != EventStatus.PLANNING:
        raise ConfirmationRefused(
            "Only an event in Planning can be confirmed. "
            f"This event is {locked.get_status_display()}."
        )
    _lock_resources(locked)
    gaps = confirmation_gaps(locked)
    if gaps:
        raise ConfirmationBlocked(gaps)

    transition_event(locked, EventStatus.CONFIRMED, actor)
    locked.confirmed_by = actor
    locked.confirmed_at = locked.status_changed_at
    locked.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])
    # SCRUM-79 AC4 - the Event Organiser and the Venue Staff and Technical
    # Support who decided this event's arrangements. A later re-confirmation
    # is a new status occurrence, so it notifies again.
    notify(
        event=locked,
        kind=NotificationKind.EVENT_CONFIRMED,
        occurrence=status_occurrence(locked),
        recipients=[locked.created_by, *involved_staff(locked)],
        message=(
            f'"{locked.name}" is confirmed. {_arrangement_summary(locked)} '
            "See the confirmed arrangements on your request."
        ),
    )
    record(actor, f"Event {locked.pk} confirmed", allowed=True, obj=locked)
    event.refresh_from_db()
    return event


# --------------------------------------------------------------------------
# AC3 - an essential resource is unavailable
# --------------------------------------------------------------------------


def involved_staff(event: EventRequest) -> list[int]:
    """Active Venue Staff and Technical Support who decided the current arrangements.

    The approvers of the event's approved venue bookings, and the staff who
    reserved its active equipment or approved its technical plan.
    """
    from apps.accounts.models import Role, User

    venue_ids = VenueBooking.objects.filter(event=event, status=BookingStatus.APPROVED).values_list(
        "decided_by_id", flat=True
    )
    tech_ids = list(
        EquipmentReservation.objects.active()
        .filter(request__plan__event=event)
        .values_list("reserved_by_id", flat=True)
    ) + list(
        TechnicalApproval.objects.filter(
            plan__event=event, status=TechnicalApprovalStatus.APPROVED
        ).values_list("approved_by_id", flat=True)
    )
    staff = User.objects.filter(is_active=True).filter(
        models.Q(pk__in=list(venue_ids), role=Role.VENUE_STAFF)
        | models.Q(pk__in=tech_ids, role=Role.TECHNICAL_SUPPORT)
    )
    return list(staff.order_by("pk").values_list("pk", flat=True))


def notify_unavailable(event: EventRequest, message: str, *, occurrence: str) -> None:
    """Tell the Event Organiser why an essential arrangement cannot be provided.

    Call inside the staff action's transaction. The event is not confirmed:
    the missing arrangement stays in ``confirmation_gaps``.
    """
    notify(
        event=event,
        kind=NotificationKind.RESOURCE_UNAVAILABLE,
        occurrence=occurrence,
        recipients=[event.created_by_id],
        message=message,
    )


@transaction.atomic
def record_equipment_unavailable(*, equipment_request, actor, reason: str) -> EquipmentHistory:
    """AC3 - Technical Support record that an equipment request cannot be met.

    The request stays unreserved, so confirmation remains blocked; the
    coordinator and the Event Organiser receive the reason.
    """
    from apps.equipment.reservations import (
        EquipmentActionError,
        notify_coordinator,
        require_technical_staff,
    )

    require_technical_staff(actor)
    if not isinstance(reason, str) or not reason.strip():
        raise EquipmentActionError(
            "Say why the equipment is unavailable.",
            status=400,
            reason=["A reason is required."],
        )
    reason = reason.strip()
    event = EventRequest.objects.select_for_update().get(pk=equipment_request.plan.event_id)
    if event.status not in (EventStatus.APPROVED, EventStatus.PLANNING):
        raise EquipmentActionError("This event is not being planned.")
    lock_equipment_types([equipment_request.equipment_type_id])
    item = (
        EquipmentRequest.objects.select_for_update()
        .select_related("plan", "equipment_type")
        .get(pk=equipment_request.pk)
    )
    if item.status != EquipmentRequestStatus.REQUESTED:
        raise EquipmentActionError("Only a request awaiting a reservation can be unavailable.")
    entry = EquipmentHistory.objects.create(
        plan=item.plan,
        request=item,
        action=EquipmentHistoryAction.UNAVAILABLE,
        plan_revision=item.plan.revision,
        before={"quantity": item.quantity},
        reason=reason,
        actor=actor,
    )
    label = f"{item.quantity} x {item.equipment_type.name}"
    notify_coordinator(event, f'{label} for "{event.name}" is unavailable: {reason}')
    notify_unavailable(
        event,
        f'{label} cannot be provided for "{event.name}", so the event is not confirmed. '
        f"Reason: {reason}",
        occurrence=f"equipment-history:{entry.pk}",
    )
    return entry
