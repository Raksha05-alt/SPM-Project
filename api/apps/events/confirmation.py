"""SCRUM-58 - confirm an event once its essential arrangements are in place.

Week 7 changes: every venue booking of the event is decided independently and
must be approved (change 3); a tentative hold is not a booking until the
coordinator confirms it (change 4); a venue that became unavailable must be
replaced or dropped (change 2); and the Safety Officer must have approved the
current arrangements (change 6).
"""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus, validate_transition
from apps.equipment.models import EquipmentRequestStatus
from apps.events.models import EventRequest
from apps.events.services import NotAssignedCoordinator, notify_status_change, transition_event
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.venues.models import BookingStatus


class ArrangementsIncomplete(Exception):
    def __init__(self, missing: list[dict]):
        super().__init__("Essential arrangements are not in place.")
        self.missing = missing


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


def _name(booking) -> str:
    if booking.session_name:
        return f"{booking.venue.name} ({booking.session_name})"
    return booking.venue.name


def _venue_label(row: dict) -> str:
    return f"{row['venue']} ({row['session']})" if row["session"] else row["venue"]


def arrangement_gaps(event: EventRequest) -> list[dict]:
    """The venue and technical arrangements that are missing, unavailable or undecided."""
    missing = []
    bookings = list(event.venue_bookings.select_related("venue"))
    approved = [b for b in bookings if b.status == BookingStatus.APPROVED]
    if not approved:
        missing.append({"arrangement": "Venue", "detail": "No venue booking has been approved."})
    for booking in bookings:
        if booking.status == BookingStatus.PENDING:
            detail = f"The request for {_name(booking)} is awaiting a decision from Venue Staff."
        elif booking.status == BookingStatus.HELD:
            if booking.hold_expired:
                detail = f"The hold on {_name(booking)} has expired."
            else:
                detail = (
                    f"{_name(booking)} is only tentatively held until "
                    f"{_when(booking.hold_expires_at)}. Confirm the hold."
                )
        elif booking.status == BookingStatus.DISRUPTED and booking.replaced_by_id is None:
            detail = (
                f"{_name(booking)} became unavailable ({booking.disruption_reason}). Request a "
                "replacement venue or withdraw the booking."
            )
        elif booking.status == BookingStatus.APPROVED and booking.review_required:
            detail = f"The booking for {_name(booking)} needs review: {booking.review_reason}"
        else:
            continue
        missing.append({"arrangement": "Venue", "detail": detail})
    requests = event.equipment_requests.exclude(
        status=EquipmentRequestStatus.WITHDRAWN
    ).select_related("equipment_type")
    for item in requests:
        label = f"{item.quantity} x {item.equipment_type.name}"
        if item.status == EquipmentRequestStatus.UNAVAILABLE:
            detail = f"{label} is unavailable: {item.unavailable_reason}"
        elif item.reserved_quantity < item.quantity:
            detail = (
                f"{label} is awaiting reservation by Technical Support Staff "
                f"({item.reserved_quantity} of {item.quantity} reserved)."
            )
        elif item.review_required:
            detail = f"{label} needs review: {item.review_reason}"
        else:
            continue
        missing.append({"arrangement": "Equipment", "detail": detail})
    return missing


def _safety_gap(event: EventRequest) -> dict | None:
    from apps.safety.models import SafetyStatus

    latest = event.safety_checks.first()
    if latest is not None and latest.status == SafetyStatus.APPROVED:
        return None
    if latest is None or latest.status == SafetyStatus.SUPERSEDED:
        detail = "The operational safety check has not been requested."
    elif latest.status == SafetyStatus.PENDING:
        detail = "The operational safety check is awaiting the Safety Officer."
    else:
        detail = (
            f"The Safety Officer {latest.get_status_display().lower()}: {latest.comment} "
            "Revise the arrangements and request a new check."
        )
    return {"arrangement": "Safety", "detail": detail}


def missing_arrangements(event: EventRequest) -> list[dict]:
    """SCRUM-58 AC2 - everything that still stands between the event and confirmation."""
    missing = arrangement_gaps(event)
    safety = _safety_gap(event)
    if safety:
        missing.append(safety)
    return missing


def readiness(event: EventRequest) -> dict:
    """The coordinator's checklist: arrangements, safety, and what can be done next."""
    from apps.safety.serializers import SafetyCheckSummarySerializer
    from apps.venues.bookings import process_holds

    process_holds()
    gaps = arrangement_gaps(event)
    latest = event.safety_checks.first()
    missing = list(gaps)
    safety = _safety_gap(event)
    if safety:
        missing.append(safety)
    from apps.safety.services import current_check

    planning = event.status == EventStatus.PLANNING
    return {
        "status": event.status,
        "arrangements": gaps,
        "safety_check": SafetyCheckSummarySerializer(latest).data if latest else None,
        "can_request_safety_check": planning and not gaps and current_check(event) is None,
        "can_confirm": planning and not missing,
        "missing": missing,
    }


def confirmed_arrangements(event: EventRequest) -> dict:
    """SCRUM-58 AC5 - what the client can rely on once the event is confirmed."""
    venues = [
        {
            "venue": b.venue.name,
            "session": b.session_name,
            "location": b.venue.location,
            "start": b.start,
            "end": b.end,
        }
        for b in event.venue_bookings.filter(status=BookingStatus.APPROVED).select_related("venue")
    ]
    equipment = [
        {"equipment": item.equipment_type.name, "quantity": item.reserved_quantity}
        for item in event.equipment_requests.filter(
            status=EquipmentRequestStatus.RESERVED
        ).select_related("equipment_type")
    ]
    return {"venues": venues, "equipment": equipment}


@transaction.atomic
def confirm_event(event: EventRequest, user) -> EventRequest:
    """SCRUM-58 AC1 / AC4 / AC5 and SCRUM-79 AC4.

    Week 7 clarification - the coordinator marks the event confirmed once they
    see every approval is in place, including the Safety Officer's.
    """
    from apps.venues.bookings import process_holds

    process_holds()
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    validate_transition(locked.status, EventStatus.CONFIRMED)
    missing = missing_arrangements(locked)
    if missing:
        raise ArrangementsIncomplete(missing)
    transition_event(locked, EventStatus.CONFIRMED, user)
    locked.confirmed_by = user
    locked.confirmed_at = timezone.now()
    locked.save(update_fields=["confirmed_by", "confirmed_at"])

    plan = confirmed_arrangements(locked)
    summary = "; ".join(
        [f"{_venue_label(v)} from {_when(v['start'])} to {_when(v['end'])}" for v in plan["venues"]]
        + [f"{e['quantity']} x {e['equipment']}" for e in plan["equipment"]]
    )
    notify_status_change(locked, EventStatus.PLANNING, user, f"Arrangements: {summary}.")
    staff = [b.decided_by for b in locked.venue_bookings.filter(status=BookingStatus.APPROVED)]
    staff += [r.reserved_by for r in locked.equipment_reservations.filter(released_at__isnull=True)]
    notify(
        staff,
        locked,
        NotificationKind.STATUS_CHANGED,
        f'"{locked.name}" is confirmed for {_when(locked.preferred_start)}.',
    )
    event.refresh_from_db()
    return event
