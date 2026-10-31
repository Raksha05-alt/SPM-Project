"""SCRUM-90 - Operational Safety Check services.

Shared contract (Sprint 3 gate G04), used by every resource action:

* ``arrangement_gaps(event)`` - venue and technical arrangements still missing.
  A safety check may be requested only when this is empty.
* ``confirmation_gaps(event)`` - the same, plus a current approved safety check.
  Final confirmation (SCRUM-58) uses this one.
* ``arrangement_version(event)`` - the version a safety check reviewed.
* ``arrangements_changed(event, reason, actor)`` - call from every action that
  changes an event's venue or equipment arrangements. It supersedes the current
  check and returns a Confirmed event to Planning.

Lock order, as agreed for cross-resource actions: event row, venue rows in ID
order, equipment-type rows in ID order, then booking/reservation rows. The
safety check row is locked after the event row.
"""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.audit import record
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequestStatus,
    ReservationStatus,
    TechnicalApprovalStatus,
)
from apps.events.models import EventRequest
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import CURRENT_STATUSES, SafetyCheck, SafetyStatus
from apps.venues.models import BookingStatus, VenueBlock

SAFETY_CHECK_ITEM = "Operational safety check"


class ConfirmationBlocked(Exception):
    """AC5 - an event cannot be confirmed; ``missing`` names each gap."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("This event cannot be confirmed yet: " + "; ".join(missing))


# --------------------------------------------------------------------------
# Reading the arrangements
# --------------------------------------------------------------------------


def safety_officers():
    return User.objects.filter(role=Role.SAFETY_OFFICER, is_active=True)


def current_check(event: EventRequest) -> SafetyCheck | None:
    """The event's pending or approved check, if any. At most one exists."""
    return event.safety_checks.filter(status__in=CURRENT_STATUSES).first()


def _equipment_plan(event: EventRequest) -> EquipmentPlan | None:
    return EquipmentPlan.objects.filter(event=event).first()


def _current_technical_approval(plan: EquipmentPlan | None):
    if plan is None:
        return None
    approval = plan.technical_approvals.filter(status=TechnicalApprovalStatus.APPROVED).first()
    # An approval of an older equipment revision does not cover the current plan.
    if approval is None or approval.plan_revision != plan.revision:
        return None
    return approval


def _open_equipment_requests(plan: EquipmentPlan | None):
    if plan is None:
        return []
    return list(
        plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN)
        .select_related("equipment_type")
        .prefetch_related("reservations")
        .order_by("pk")
    )


def _active_reservation(equipment_request):
    for reservation in equipment_request.reservations.all():
        if reservation.status == ReservationStatus.ACTIVE:
            return reservation
    return None


def _approved_bookings(event: EventRequest):
    # A collection, not a single venue: SCRUM-87 adds parallel sessions later.
    return list(
        event.venue_bookings.filter(status=BookingStatus.APPROVED)
        .select_related("venue")
        .order_by("starts_at", "pk")
    )


def arrangement_gaps(event: EventRequest) -> list[str]:
    """AC1 - venue and technical arrangements that are not yet in place.

    An empty list means a safety check may be requested. Each gap names the
    actual record, so the coordinator knows what to fix.
    """
    gaps = []
    bookings = list(event.venue_bookings.select_related("venue").order_by("pk"))
    approved = [b for b in bookings if b.status == BookingStatus.APPROVED]
    if not approved:
        gaps.append("Venue: no venue booking has been approved by Venue Staff.")
    for booking in bookings:
        if booking.status == BookingStatus.PENDING:
            gaps.append(
                f"Venue: the booking request for {booking.venue.name} is still awaiting Venue Staff."
            )
    for booking in approved:
        venue = booking.venue
        if not venue.in_service:
            gaps.append(f"Venue: {venue.name} is out of service.")
        blocks = VenueBlock.objects.filter(
            venue=venue, starts_at__lt=booking.ends_at, ends_at__gt=booking.starts_at
        ).order_by("starts_at", "pk")
        for block in blocks:
            gaps.append(
                f"Venue: {venue.name} is blocked during the booked period ({block.reason})."
            )

    plan = _equipment_plan(event)
    if _current_technical_approval(plan) is None:
        gaps.append("Technical: the equipment plan has not been approved by Technical Support.")
    for item in _open_equipment_requests(plan):
        if item.status != EquipmentRequestStatus.RESERVED or _active_reservation(item) is None:
            gaps.append(
                f"Equipment: {item.quantity} x {item.equipment_type.name} "
                "is requested but not reserved."
            )
    return gaps


def arrangement_version(event: EventRequest) -> str:
    """The version of everything a safety approval depends on.

    Date, time and attendance (Week 7 clarification), each approved venue
    booking, and the approved equipment plan with its reservations. Any change
    produces a different value, so an approval of an older version can never
    permit confirmation, even if a resource action failed to call
    ``arrangements_changed``.
    """
    plan = _equipment_plan(event)
    approval = _current_technical_approval(plan)
    equipment = []
    for item in _open_equipment_requests(plan):
        reservation = _active_reservation(item)
        equipment.append(
            [
                item.pk,
                item.equipment_type_id,
                item.quantity,
                item.status,
                reservation.pk if reservation else None,
                reservation.quantity if reservation else None,
            ]
        )
    payload = {
        "start": event.preferred_start,
        "end": event.preferred_end,
        "attendance": event.expected_attendance,
        "venues": [
            [b.pk, b.venue_id, b.starts_at, b.ends_at, b.attendance, b.layout]
            for b in _approved_bookings(event)
        ],
        "technical_approval": [approval.pk, approval.plan_revision] if approval else None,
        "equipment": equipment,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def is_stale(check: SafetyCheck, event: EventRequest | None = None) -> bool:
    """True when the check reviewed a different arrangement version."""
    return check.arrangement_version != arrangement_version(event or check.event)


def confirmation_gaps(event: EventRequest) -> list[str]:
    """AC5 - arrangement gaps plus a current approved safety check.

    SCRUM-58's confirm action may add its own items to this list.
    """
    gaps = arrangement_gaps(event)
    check = current_check(event)
    if check is None:
        gaps.append(f"{SAFETY_CHECK_ITEM}: no approved check.")
    elif check.status == SafetyStatus.PENDING:
        gaps.append(f"{SAFETY_CHECK_ITEM}: still awaiting a Safety Officer.")
    elif is_stale(check, event):
        gaps.append(
            f"{SAFETY_CHECK_ITEM}: the arrangements changed after it was approved. "
            "Request a new check."
        )
    return gaps


def ensure_can_confirm(event: EventRequest) -> None:
    """Raise ConfirmationBlocked unless the event may be confirmed.

    ``apps.events.services.transition_event`` calls this for every move to
    Confirmed, so no confirm action can skip it (fail-closed).
    """
    gaps = confirmation_gaps(event)
    if gaps:
        raise ConfirmationBlocked(gaps)


# --------------------------------------------------------------------------
# Invalidation
# --------------------------------------------------------------------------


def _notify(recipients, event: EventRequest, kind: str, message: str, *, skip=None) -> None:
    unique = {}
    for person in recipients:
        if person is not None and person.pk != getattr(skip, "pk", None):
            unique[person.pk] = person
    Notification.objects.bulk_create(
        [
            Notification(recipient=person, event=event, kind=kind, message=message)
            for person in unique.values()
        ]
    )


def _supersede(check: SafetyCheck, event: EventRequest, reason: str, actor) -> SafetyCheck:
    """Mark a pending or approved check Superseded, keeping its decision on record."""
    was_pending = check.status == SafetyStatus.PENDING
    check.status = SafetyStatus.SUPERSEDED
    check.superseded_at = timezone.now()
    check.superseded_reason = reason
    check.save(update_fields=["status", "superseded_at", "superseded_reason"])
    recipients = [event.coordinator]
    if was_pending:
        recipients += list(safety_officers())
    _notify(
        recipients,
        event,
        NotificationKind.SAFETY_SUPERSEDED,
        f'The safety check for "{event.name}" no longer applies: {reason} '
        "A new check is needed before the event can be confirmed.",
        skip=actor,
    )
    return check


@transaction.atomic
def arrangements_changed(event: EventRequest, reason: str, actor) -> SafetyCheck | None:
    """AC6 - every change to a venue or equipment arrangement goes through here.

    Supersedes the current check and returns a Confirmed event to Planning, so
    it is checked and confirmed again. Call it inside the transaction that
    changed the arrangements; if that transaction rolls back, so does this.

    Producers: booking status changes (``apps.venues.bookings.transition_booking``,
    used by SCRUM-72 decisions and SCRUM-67 withdrawal), equipment reservation,
    release and amendment (SCRUM-16/77/75), and later approved change requests
    (SCRUM-80). Returns the superseded check, or None if none was current.
    """
    from apps.events.services import transition_event

    # Serialises with Safety decisions, which lock the event row first.
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    check = (
        SafetyCheck.objects.select_for_update()
        .filter(event=locked, status__in=CURRENT_STATUSES)
        .first()
    )
    superseded = _supersede(check, locked, reason, actor) if check else None
    if locked.status == EventStatus.CONFIRMED:
        transition_event(locked, EventStatus.PLANNING, actor)
        record(
            actor,
            f"Event {locked.pk} returned to Planning",
            allowed=True,
            obj=locked,
            detail=reason,
        )
        _notify(
            [locked.coordinator, locked.created_by],
            locked,
            NotificationKind.PLANNING_REOPENED,
            f'"{locked.name}" is back in planning while its arrangements are updated: {reason}',
            skip=actor,
        )
    event.refresh_from_db()
    return superseded
