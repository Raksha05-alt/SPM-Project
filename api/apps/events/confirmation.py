"""SCRUM-58 - confirm an event once its essential arrangements are in place."""

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


def missing_arrangements(event: EventRequest) -> list[dict]:
    """SCRUM-58 AC2 - every essential arrangement that is missing, unavailable or undecided."""
    missing = []
    bookings = list(event.venue_bookings.select_related("venue"))
    approved = [b for b in bookings if b.status == BookingStatus.APPROVED]
    if not approved:
        pending = [b for b in bookings if b.status == BookingStatus.PENDING]
        if pending:
            for booking in pending:
                missing.append(
                    {
                        "arrangement": "Venue",
                        "detail": f"The request for {booking.venue.name} is awaiting a decision "
                        "from Venue Staff.",
                    }
                )
        else:
            missing.append(
                {"arrangement": "Venue", "detail": "No venue booking has been approved."}
            )
    for booking in approved:
        if booking.review_required:
            missing.append(
                {
                    "arrangement": "Venue",
                    "detail": f"The booking for {booking.venue.name} needs review: "
                    f"{booking.review_reason}",
                }
            )
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


def confirmed_arrangements(event: EventRequest) -> dict:
    """SCRUM-58 AC5 - what the client can rely on once the event is confirmed."""
    venues = [
        {
            "venue": b.venue.name,
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
    """SCRUM-58 AC1 / AC4 / AC5 and SCRUM-79 AC4."""
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
        [f"{v['venue']} from {_when(v['start'])} to {_when(v['end'])}" for v in plan["venues"]]
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
