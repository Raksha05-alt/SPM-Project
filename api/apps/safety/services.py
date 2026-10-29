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

Workflow (gate G20): ``request_check`` by the assigned coordinator,
``safety_facts`` for the Safety Officer's review, and ``decide``.

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
from apps.events.models import EventRequest, RoomLayout
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import CURRENT_STATUSES, DECISIONS, SafetyCheck, SafetyStatus
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


# --------------------------------------------------------------------------
# Workflow (Sprint 3 gate G20): request, review facts and decisions
# --------------------------------------------------------------------------


class SafetyRefused(Exception):
    """A safety action that is not possible right now, with any detail to show."""

    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


class NotSafetyOfficer(Exception):
    """AC7 - only an active Safety Officer may decide a check."""


def _layout_label(value: str) -> str:
    return RoomLayout(value).label if value in RoomLayout.values else "No preference"


def _iso(value):
    return value.isoformat() if value else None


def _name(user):
    return (user.get_full_name() or user.email) if user else None


def safety_facts(event: EventRequest) -> dict:
    """AC2 - what the Safety Officer reviews.

    Expected attendance, each venue's capacity and layout, emergency access and
    known restrictions, accessibility requirements and the equipment to be
    placed. Missing venue safety information is shown as missing, never
    invented. ``concerns`` points out what the recorded facts already show; the
    Safety Officer still makes the decision (no automatic approval).
    """
    venues, concerns = [], []
    accessibility_needed = bool((event.accessibility_needs or "").strip())
    for booking in _approved_bookings(event):
        venue = booking.venue
        venues.append(
            {
                "booking": booking.pk,
                "venue": venue.name,
                "location": venue.location,
                "capacity": venue.capacity,
                "booked_attendance": booking.attendance,
                "layout": _layout_label(booking.layout),
                "starts_at": _iso(booking.starts_at),
                "ends_at": _iso(booking.ends_at),
                "wheelchair_access": venue.wheelchair_access,
                "accessibility_notes": venue.accessibility_notes,
                "required_facilities": booking.required_facilities,
                "wheelchair_access_required": booking.wheelchair_access_required,
                "booking_accessibility_notes": booking.accessibility_notes,
                "emergency_access": venue.emergency_access,
                "known_restrictions": venue.known_restrictions,
            }
        )
        if booking.attendance > venue.capacity:
            concerns.append(
                f"{venue.name}: {booking.attendance} people booked for a capacity of "
                f"{venue.capacity}."
            )
        if not venue.emergency_access.strip():
            concerns.append(f"{venue.name} has no emergency access information recorded.")
        if not venue.known_restrictions.strip():
            concerns.append(f"{venue.name} has no known restrictions recorded.")
        if (accessibility_needed or booking.wheelchair_access_required) and (
            venue.wheelchair_access is not True
        ):
            concerns.append(
                f"{venue.name} has no recorded wheelchair access, "
                "and the event has accessibility requirements."
            )
    total_capacity = sum(v["capacity"] for v in venues)
    attendance = event.expected_attendance or 0
    if venues and attendance > total_capacity:
        concerns.append(
            f"Expected attendance of {attendance} exceeds the combined venue capacity "
            f"of {total_capacity}."
        )

    plan = _equipment_plan(event)
    approval = _current_technical_approval(plan)
    equipment = []
    for item in _open_equipment_requests(plan):
        reservation = _active_reservation(item)
        equipment.append(
            {
                "equipment": item.equipment_type.name,
                "quantity": item.quantity,
                "reserved_quantity": reservation.quantity if reservation else 0,
                "status": item.get_status_display(),
                "technical_requirements": item.technical_requirements,
            }
        )

    return {
        "event": event.pk,
        "event_name": event.name,
        "organisation": event.organisation.name,
        "expected_attendance": event.expected_attendance,
        "starts_at": _iso(event.preferred_start),
        "ends_at": _iso(event.preferred_end),
        "required_layout": _layout_label(event.required_layout),
        "accessibility_needs": event.accessibility_needs,
        "venues": venues,
        "equipment": equipment,
        "technical_approval": (
            {
                "approved_by": _name(approval.approved_by),
                "approved_at": _iso(approval.approved_at),
                "no_equipment_required": approval.no_equipment_required,
                "notes": approval.notes,
            }
            if approval
            else None
        ),
        "concerns": concerns,
    }


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}" if moment else "a date not yet set"


STALE_REQUEST_REASON = "The arrangements changed after it was requested."


@transaction.atomic
def request_check(event: EventRequest, actor, note: str = "") -> SafetyCheck:
    """AC1 - the assigned coordinator sends a planned event to the Safety Officers.

    Uses ``arrangement_gaps``, never ``confirmation_gaps``: requesting a check
    needs approved arrangements, not an already approved check.
    """
    from apps.events.services import NotAssignedCoordinator

    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    # Reread the current assignment under the lock (SCRUM-89 ownership contract).
    if not actor.is_coordinator or event.coordinator_id != actor.pk:
        raise NotAssignedCoordinator
    if event.status != EventStatus.PLANNING:
        raise SafetyRefused(
            "A safety check can only be requested while the event is in Planning. "
            f"This event is {event.get_status_display()}."
        )
    gaps = arrangement_gaps(event)
    if gaps:
        raise SafetyRefused(
            "The venue and technical arrangements must all be in place before a safety check.",
            arrangement_gaps=gaps,
        )
    existing = (
        SafetyCheck.objects.select_for_update()
        .filter(event=event, status__in=CURRENT_STATUSES)
        .first()
    )
    if existing is not None:
        if not is_stale(existing, event):
            raise SafetyRefused(
                "This event already has a safety check that is "
                f"{existing.get_status_display().lower()}."
            )
        # A producer changed the arrangements without superseding it. Do so now.
        _supersede(existing, event, STALE_REQUEST_REASON, actor)

    check = SafetyCheck.objects.create(
        event=event,
        requested_by=actor,
        request_note=(note or "").strip(),
        facts=safety_facts(event),
        arrangement_version=arrangement_version(event),
    )
    _notify(
        safety_officers(),
        event,
        NotificationKind.SAFETY_REQUESTED,
        f'"{event.name}" on {_when(event.preferred_start)} is ready for an '
        "operational safety check.",
    )
    record(actor, f"Safety check requested for event {event.pk}", allowed=True, obj=check)
    return check


def decide(check: SafetyCheck, actor, decision: str, comment: str = "") -> SafetyCheck:
    """AC3/AC4 - a Safety Officer approves, rejects or requests changes.

    A comment is required to reject or request changes. Either way the event
    stays in Planning: the coordinator revises the arrangements and requests a
    new check. A decision on a check whose arrangement version has changed is
    refused, and that check is superseded.
    """
    if not (actor.is_safety_officer and actor.is_active):
        raise NotSafetyOfficer
    if decision not in DECISIONS:
        raise SafetyRefused("Choose approve, reject or request changes.", status=400)
    comment = (comment or "").strip()
    if decision != SafetyStatus.APPROVED and not comment:
        raise SafetyRefused(
            "Add a comment saying what is unsafe or what must change.",
            status=400,
            comment=["A comment is required to reject or request changes."],
        )

    with transaction.atomic():
        event = EventRequest.objects.select_for_update().get(pk=check.event_id)
        check = SafetyCheck.objects.select_for_update().get(pk=check.pk)
        if check.status != SafetyStatus.PENDING:
            raise SafetyRefused(
                f"This safety check is already {check.get_status_display().lower()}."
            )
        stale = is_stale(check, event)
        if stale:
            # Commit the supersession; the refusal is raised after the transaction.
            _supersede(check, event, STALE_REQUEST_REASON, actor)
        else:
            check.status = decision
            check.decided_by = actor
            check.decided_at = timezone.now()
            check.comment = comment
            check.save(update_fields=["status", "decided_by", "decided_at", "comment"])
            if decision == SafetyStatus.APPROVED:
                message = (
                    f'The safety check for "{event.name}" is approved. '
                    "The event can now be confirmed."
                )
            else:
                message = (
                    f'The safety check for "{event.name}" was '
                    f"{check.get_status_display().lower()}: {comment} "
                    "The event stays in planning. Revise the venue or technical "
                    "arrangements and request a new check."
                )
            _notify(
                [event.coordinator, event.supervising_lead],
                event,
                NotificationKind.SAFETY_DECIDED,
                message,
            )
            record(
                actor,
                f"Safety check {check.pk} decided",
                allowed=True,
                obj=check,
                detail=f"decision={decision}",
            )
    if stale:
        raise SafetyRefused(
            "The event's arrangements changed after this check was requested, so it no "
            "longer applies. The coordinator must request a new check."
        )
    return check
