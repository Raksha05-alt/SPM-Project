"""Week 7 change 6 - requesting, deciding and invalidating Operational Safety Checks."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventChangeLog, EventRequest
from apps.events.services import NotAssignedCoordinator, NotPermitted, reopen_planning
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.safety.models import CURRENT_STATUSES, DECISIONS, SafetyCheck, SafetyStatus


class SafetyRefused(Exception):
    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


def safety_officers():
    return User.objects.filter(role=Role.SAFETY_OFFICER, is_active=True)


def current_check(event: EventRequest) -> SafetyCheck | None:
    return event.safety_checks.filter(status__in=CURRENT_STATUSES).first()


def is_approved(event: EventRequest) -> bool:
    return event.safety_checks.filter(status=SafetyStatus.APPROVED).exists()


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}" if moment else "not set"


def safety_facts(event: EventRequest) -> dict:
    """What the Safety Officer reviews: attendance, each venue's capacity, layout,
    access and known restrictions, the equipment to be placed, and any concern
    the system can see from the recorded facts. The officer decides; the system
    only gathers and points out."""
    from apps.equipment.models import EquipmentRequestStatus
    from apps.venues.models import BookingStatus, layout_label

    attendance = event.expected_attendance or 0
    venues, concerns = [], []
    for b in event.venue_bookings.filter(status=BookingStatus.APPROVED).select_related("venue"):
        venue = b.venue
        venues.append(
            {
                "booking": b.pk,
                "venue": venue.name,
                "session": b.session_name,
                "location": venue.location,
                "capacity": venue.capacity,
                "attendance": b.attendance,
                "layout": layout_label(b.layout),
                "start": b.start,
                "end": b.end,
                "occupied_from": b.occupied_start,
                "occupied_until": b.occupied_end,
                "wheelchair_access": venue.wheelchair_access,
                "accessibility_notes": venue.accessibility_notes,
                "safety_notes": venue.safety_notes,
            }
        )
        if b.attendance > venue.capacity:
            concerns.append(
                f"{venue.name}: {b.attendance} attendees booked for a capacity of {venue.capacity}."
            )
        if (event.accessibility_needs or "").strip() and venue.wheelchair_access is not True:
            concerns.append(f"{venue.name} has no recorded step-free access.")
        if not venue.safety_notes.strip():
            concerns.append(f"{venue.name} has no emergency access or restriction notes recorded.")
    total_capacity = sum(v["capacity"] for v in venues)
    if venues and attendance > total_capacity:
        concerns.append(
            f"Expected attendance of {attendance} exceeds the combined capacity of {total_capacity}."
        )
    equipment = [
        {
            "equipment": item.equipment_type.name,
            "quantity": item.reserved_quantity,
            "technical_requirements": item.technical_requirements,
        }
        for item in event.equipment_requests.filter(
            status=EquipmentRequestStatus.RESERVED
        ).select_related("equipment_type")
    ]
    return {
        "event": event.pk,
        "event_name": event.name,
        "expected_attendance": event.expected_attendance,
        "required_layout": layout_label(event.required_layout),
        "accessibility_needs": event.accessibility_needs,
        "start": event.preferred_start,
        "end": event.preferred_end,
        "venues": venues,
        "equipment": equipment,
        "concerns": concerns,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


@transaction.atomic
def request_check(event: EventRequest, user, note: str = "") -> SafetyCheck:
    """The coordinator sends the planned event to the Safety Officers.

    Only once the venue and technical arrangements are in place, and only one
    check at a time.
    """
    from apps.events.confirmation import arrangement_gaps

    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if event.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if event.status != EventStatus.PLANNING:
        raise SafetyRefused(
            f"A safety check is requested during planning; the event is {event.get_status_display()}."
        )
    gaps = arrangement_gaps(event)
    if gaps:
        raise SafetyRefused(
            "The venue and technical arrangements must be in place before the safety check.",
            missing=gaps,
        )
    existing = current_check(event)
    if existing is not None:
        raise SafetyRefused(
            f"This event already has a safety check that is {existing.get_status_display().lower()}."
        )
    check = SafetyCheck.objects.create(
        event=event,
        requested_by=user,
        request_note=(note or "").strip(),
        facts=_json_safe(safety_facts(event)),
    )
    notify(
        safety_officers(),
        event,
        NotificationKind.SAFETY_REQUESTED,
        f'"{event.name}" on {_when(event.preferred_start)} is ready for an operational safety check.',
    )
    return check


@transaction.atomic
def decide(check: SafetyCheck, user, decision: str, comment: str = "") -> SafetyCheck:
    """The Safety Officer approves, rejects or requests changes, with a comment.

    Rejecting and requesting changes both send the event back to the planning
    stage (Week 7 clarification): the coordinator revises the affected
    arrangements and requests a new check.
    """
    if not user.is_safety_officer:
        raise NotPermitted
    check = SafetyCheck.objects.select_for_update().select_related("event").get(pk=check.pk)
    if decision not in DECISIONS:
        raise SafetyRefused("Choose approve, reject or request changes.", status=400)
    if check.status != SafetyStatus.PENDING:
        raise SafetyRefused(f"This safety check is already {check.get_status_display().lower()}.")
    comment = (comment or "").strip()
    if decision != SafetyStatus.APPROVED and not comment:
        raise SafetyRefused("Say what is unsafe or what must change.", status=400)
    event = EventRequest.objects.select_for_update().get(pk=check.event_id)
    check.status = decision
    check.decided_by = user
    check.decided_at = timezone.now()
    check.comment = comment
    check.save()
    outcome = check.get_status_display()
    EventChangeLog.objects.create(
        event=event,
        field="Operational safety check",
        previous_value="Awaiting Safety Officer",
        new_value=f"{outcome}: {comment}" if comment else outcome,
        changed_by=user,
        significant=decision != SafetyStatus.APPROVED,
    )
    if decision == SafetyStatus.APPROVED:
        message = f'The safety check for "{event.name}" is approved. You can confirm the event.'
    else:
        message = (
            f'The safety check for "{event.name}" was {outcome.lower()}: {comment} '
            "The event stays in planning; revise the affected arrangements and request a new check."
        )
    notify([event.coordinator, event.assigned_by], event, NotificationKind.SAFETY_DECIDED, message)
    return check


def invalidate(event: EventRequest, user, reason: str) -> SafetyCheck | None:
    """A pending or approved check no longer describes the arrangements: supersede it.

    Call inside the transaction that changed the arrangements.
    """
    check = current_check(event)
    if check is None:
        return None
    was_pending = check.status == SafetyStatus.PENDING
    check.status = SafetyStatus.SUPERSEDED
    check.superseded_at = timezone.now()
    check.superseded_reason = reason
    check.save(update_fields=["status", "superseded_at", "superseded_reason"])
    message = (
        f'The safety check for "{event.name}" no longer applies: {reason} '
        "A new check is needed before the event can be confirmed."
    )
    recipients = [event.coordinator]
    if was_pending:
        recipients += list(safety_officers())
    notify(
        [u for u in recipients if u and u.pk != getattr(user, "pk", None)],
        event,
        NotificationKind.SAFETY_DECIDED,
        message,
    )
    return check


def arrangements_changed(event: EventRequest, user, reason: str) -> None:
    """Every change to a venue or equipment arrangement goes through here.

    The safety check is superseded, and a confirmed event goes back to planning
    so that it is approved and confirmed again (Week 7 changes 2, 3 and 6).
    Call inside a transaction.
    """
    invalidate(event, user, reason)
    reopen_planning(event, user, reason)
