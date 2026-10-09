"""What an event change does to the arrangements already made for it.

SCRUM-59 significant changes, SCRUM-66 suitability re-check, SCRUM-70 venue
conflicts after a date or time change, SCRUM-78 impact of a change request,
SCRUM-80 staff review of affected arrangements and SCRUM-18 attendee notices.
"""

from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequestStatus
from apps.equipment.services import available_quantity, technical_staff
from apps.events.models import EventRequest
from apps.events.services import log_changes
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.registrations.models import RegistrationStatus
from apps.venues.bookings import clashes, overlapping_blocks, venue_staff
from apps.venues.models import BookingStatus
from apps.venues.suitability import assess

TIMING = frozenset({"preferred_start", "preferred_end"})
VENUE_NEEDS = frozenset({"expected_attendance", "required_layout", "accessibility_needs"})
EQUIPMENT_NEEDS = frozenset({"equipment_notes"})
SIGNIFICANT = TIMING | VENUE_NEEDS | EQUIPMENT_NEEDS

FIELD_LABELS = {
    "preferred_start": "start time",
    "preferred_end": "end time",
    "expected_attendance": "expected attendance",
    "required_layout": "room layout",
    "accessibility_needs": "accessibility needs",
    "equipment_notes": "equipment requirements",
}

ACTIVE_BOOKINGS = (BookingStatus.PENDING, BookingStatus.APPROVED)
SUITABILITY_CRITERIA = ("Capacity", "Room layout", "Accessibility")


def when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


def period(start, end) -> str:
    return f"{when(start)} to {when(end)}"


def shifted(booking, old: dict, new: dict):
    """The booking moved by as much as the event moved (SCRUM-70)."""
    if not (old["preferred_start"] and new["preferred_start"]):
        return booking.start, booking.end
    start = booking.start + (new["preferred_start"] - old["preferred_start"])
    end = booking.end + (new["preferred_end"] - old["preferred_end"])
    if end <= start:
        return new["preferred_start"], new["preferred_end"]
    return start, end


def unsuitable(venue, values: dict) -> list[str]:
    """SCRUM-66 - reasons the venue no longer suits the event's capacity, layout or access."""
    needs = {
        "attendance": values["expected_attendance"],
        "layout": values["required_layout"],
        "accessibility_needs": values["accessibility_needs"],
    }
    return [
        check["reason"]
        for check in assess(venue, needs)
        if check["criterion"] in SUITABILITY_CRITERIA and not check["matches"]
    ]


def venue_conflicts(booking, start, end) -> list[dict]:
    rows = [
        {"event": c.event_id, "event_name": c.event.name, "start": c.start, "end": c.end}
        for c in clashes(booking.venue_id, start, end, event_id=booking.event_id)
    ]
    rows += [
        {"event": None, "event_name": f"Blocked: {b.reason}", "start": b.start, "end": b.end}
        for b in overlapping_blocks(booking.venue, start, end)
    ]
    return rows


def _values(event: EventRequest, overrides: dict | None = None) -> dict:
    values = {field: getattr(event, field) for field in SIGNIFICANT}
    values.update(overrides or {})
    return values


# --- SCRUM-78 - impact of a pending change request --------------------------------


def impact_of(event: EventRequest, proposed: dict) -> dict:
    old = _values(event)
    new = _values(event, proposed)
    changed = {field for field in proposed if old[field] != new[field]}
    bookings, equipment, registrations = [], [], None

    if changed & (TIMING | VENUE_NEEDS):
        for booking in event.venue_bookings.filter(status__in=ACTIVE_BOOKINGS).select_related(
            "venue"
        ):
            start, end = (
                shifted(booking, old, new) if changed & TIMING else (booking.start, booking.end)
            )
            issues = unsuitable(booking.venue, new) if changed & VENUE_NEEDS else []
            conflicts = venue_conflicts(booking, start, end) if changed & TIMING else []
            bookings.append(
                {
                    "booking": booking.pk,
                    "venue": booking.venue.name,
                    "status": booking.get_status_display(),
                    "current_start": booking.start,
                    "current_end": booking.end,
                    "new_start": start,
                    "new_end": end,
                    "potentially_unsuitable": bool(issues),
                    "issues": issues,
                    "conflicts": conflicts,
                }
            )

    if changed & (TIMING | EQUIPMENT_NEEDS):
        for item in event.equipment_requests.exclude(
            status=EquipmentRequestStatus.WITHDRAWN
        ).select_related("equipment_type"):
            row = {
                "request": item.pk,
                "equipment": item.equipment_type.name,
                "quantity": item.quantity,
                "reserved_quantity": item.reserved_quantity,
                "issues": [],
            }
            if changed & TIMING and new["preferred_start"] and new["preferred_end"]:
                available = available_quantity(
                    item.equipment_type,
                    new["preferred_start"],
                    new["preferred_end"],
                    exclude_event_id=event.pk,
                )
                row["available_in_new_period"] = available
                if available < item.quantity:
                    row["issues"].append(
                        f"Only {available} available in the new period; {item.quantity} needed."
                    )
            equipment.append(row)

    if changed & (TIMING | {"expected_attendance"}):
        registered = event.registrations.filter(status=RegistrationStatus.REGISTERED).count()
        waitlisted = event.registrations.filter(status=RegistrationStatus.WAITLISTED).count()
        if registered or waitlisted:
            registrations = {"registered": registered, "waitlisted": waitlisted, "issues": []}
            if "expected_attendance" in changed and new["expected_attendance"] < registered:
                registrations["issues"].append(
                    f"{registered} attendees are already registered, more than the new "
                    f"expected attendance of {new['expected_attendance']}."
                )

    has_impact = bool(bookings or equipment or registrations)
    return {
        "changed_fields": sorted(FIELD_LABELS[f] for f in changed),
        "venue_bookings": bookings,
        "equipment": equipment,
        "registrations": registrations,
        "has_impact": has_impact,
        "message": None if has_impact else "This change does not affect any existing arrangements.",
    }


# --- SCRUM-59 / 66 / 70 / 80 AC1 / 18 - after a change has been saved -------------


def _flag(obj, reasons: list[str], now, **extra):
    obj.review_required = True
    obj.review_reason = " ".join(reasons)
    obj.review_flagged_at = now
    for field, value in extra.items():
        setattr(obj, field, value)
    obj.save()


def registered_attendees(event: EventRequest):
    return [r.attendee for r in event.registrations.filter(status=RegistrationStatus.REGISTERED)]


def describe_for_attendees(event: EventRequest) -> str:
    venues = ", ".join(
        b.venue.name
        for b in event.venue_bookings.filter(status=BookingStatus.APPROVED).select_related("venue")
    )
    where = f" at {venues}" if venues else ""
    return f"It now runs from {period(event.preferred_start, event.preferred_end)}{where}."


def apply_change(event: EventRequest, before: dict, user, *, change_request=None) -> dict:
    """Record the change and send each affected arrangement for review where needed."""
    changed = {field for field in before if getattr(event, field) != before[field]}
    significant = changed & SIGNIFICANT
    review_all = bool(significant) and (
        event.status == EventStatus.CONFIRMED or change_request is not None
    )
    log_changes(event, before, user, significant=SIGNIFICANT if review_all else frozenset())
    if not changed & SIGNIFICANT:
        return {"significant": False, "changed_fields": [], "affected_arrangements": []}

    labels = ", ".join(sorted(FIELD_LABELS[f] for f in significant))
    general = f"The event's {labels} changed."
    old = _values(event, {field: before[field] for field in SIGNIFICANT if field in before})
    new = _values(event)
    now = timezone.now()
    affected, venue_flags, equipment_flags = [], [], []

    for booking in event.venue_bookings.filter(status__in=ACTIVE_BOOKINGS).select_related("venue"):
        reasons, extra = [], {}
        approved = booking.status == BookingStatus.APPROVED
        if approved and changed & VENUE_NEEDS:
            reasons += unsuitable(booking.venue, new)
        if approved and changed & TIMING:
            start, end = shifted(booking, old, new)
            extra = {"review_start": start, "review_end": end}
            conflicts = venue_conflicts(booking, start, end)
            if conflicts:
                names = ", ".join(c["event_name"] for c in conflicts)
                reasons.append(f"The new period {period(start, end)} overlaps {names}.")
            elif review_all:
                reasons.append(
                    f"The event has moved; the new period {period(start, end)} has no "
                    "conflicting bookings."
                )
        if review_all and not reasons and changed & (TIMING | VENUE_NEEDS):
            reasons.append(general)
        if reasons:
            _flag(booking, reasons, now, **extra)
            venue_flags.append(booking)
            affected.append(f"Venue booking for {booking.venue.name}")

    if changed & (TIMING | EQUIPMENT_NEEDS):
        for item in event.equipment_requests.exclude(
            status=EquipmentRequestStatus.WITHDRAWN
        ).select_related("equipment_type"):
            reasons = []
            reserved = item.reserved_quantity
            if changed & TIMING and reserved:
                available = available_quantity(
                    item.equipment_type,
                    event.preferred_start,
                    event.preferred_end,
                    exclude_event_id=event.pk,
                )
                if available < reserved:
                    reasons.append(
                        f"Only {available} available in the new period; {reserved} reserved."
                    )
            if review_all and not reasons:
                reasons.append(general)
            if reasons:
                _flag(item, reasons, now)
                equipment_flags.append(item)
                affected.append(f"{item.quantity} x {item.equipment_type.name}")

    for booking in venue_flags:
        notify(
            [*venue_staff(), event.coordinator],
            event,
            NotificationKind.REVIEW_NEEDED,
            f'The booking of {booking.venue.name} for "{event.name}" needs review: '
            f"{booking.review_reason}",
        )
    for item in equipment_flags:
        notify(
            [*technical_staff(), event.coordinator],
            event,
            NotificationKind.REVIEW_NEEDED,
            f'{item.equipment_type.name} for "{event.name}" needs review: {item.review_reason}',
        )

    attendees = registered_attendees(event)
    if attendees and review_all:
        affected.append(f"{len(attendees)} registered attendee(s)")
    if review_all and event.created_by_id != user.pk:
        notify(
            [event.created_by],
            event,
            NotificationKind.EVENT_CHANGED,
            f'"{event.name}" has a significant change: {general}',
        )
    if event.status == EventStatus.CONFIRMED and changed & TIMING:
        # SCRUM-18 AC1-AC4 - only Attendees still registered hear about it.
        notify(
            attendees,
            event,
            NotificationKind.EVENT_CHANGED,
            f'The date or time of "{event.name}" has changed. {describe_for_attendees(event)}',
        )
    return {
        "significant": review_all,
        "changed_fields": sorted(FIELD_LABELS[f] for f in significant),
        "affected_arrangements": affected,
    }
