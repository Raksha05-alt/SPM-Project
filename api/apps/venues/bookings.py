"""SCRUM-11 venue booking contract (Sprint 3 gate G02).

Shared rules for venue booking records, used by the later booking actions:

* ``validate_booking_request`` - the structural checks every request must pass.
* ``create_booking_record`` - persist a Pending booking and its first history row.
* ``transition_booking`` - the only way a booking's status changes.

This module does not decide who may act, whether the venue suits the event or
whether it is free. Those belong to the actions built on it: the coordinator's
request action (SCRUM-11, gate G09) adds the assigned-coordinator, suitability
(SCRUM-71) and occupancy (SCRUM-69) checks; Venue Staff decisions (SCRUM-72)
and withdrawal (SCRUM-67) add theirs before calling ``transition_booking``.

Lock order for cross-resource actions: event row, venue rows in ID order, then
booking rows.
"""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.models import RoomLayout
from apps.venues.models import BookingStatus, VenueBooking, VenueBookingHistory
from apps.venues.serializers import is_facility_list, normalise_facilities

# Sprint 3 booking lifecycle. Sprint 4 adds Held/Expired/Disrupted here.
ALLOWED_BOOKING_TRANSITIONS: dict[str, frozenset[str]] = {
    BookingStatus.PENDING: frozenset(
        {BookingStatus.APPROVED, BookingStatus.REJECTED, BookingStatus.WITHDRAWN}
    ),
    BookingStatus.APPROVED: frozenset({BookingStatus.WITHDRAWN}),
    BookingStatus.REJECTED: frozenset(),
    BookingStatus.WITHDRAWN: frozenset(),
}

# A venue cannot be requested for a private draft or a finished event.
EVENT_STATUSES_CLOSED_TO_BOOKING = frozenset(
    {
        EventStatus.DRAFT,
        EventStatus.REJECTED,
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
    }
)


class BookingValidationError(Exception):
    """Every problem with a booking request, as {field: message}."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))


class InvalidBookingTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(
            f"A {BookingStatus(current).label} booking cannot become {BookingStatus(target).label}."
        )


def validate_booking_request(
    *,
    event,
    venue,
    starts_at,
    ends_at,
    attendance,
    layout="",
    required_facilities=None,
    wheelchair_access_required=False,
    accessibility_notes="",
) -> dict:
    """Return the cleaned values, or raise BookingValidationError naming every problem.

    SCRUM-11 AC3 - missing or invalid required information is identified item
    by item, rather than stopping at the first problem.
    """
    errors: dict[str, str] = {}

    if event is None:
        errors["event"] = "Choose the event this venue is for."
    elif event.status in EVENT_STATUSES_CLOSED_TO_BOOKING:
        errors["event"] = f"A venue cannot be requested for a {event.get_status_display()} event."
    if venue is None:
        errors["venue"] = "Choose a venue."

    for field, value in (("starts_at", starts_at), ("ends_at", ends_at)):
        if value is None:
            errors[field] = "Enter the event date and time."
        elif not hasattr(value, "tzinfo") or timezone.is_naive(value):
            errors[field] = "Give a date and time with its time zone."
    if "starts_at" not in errors and "ends_at" not in errors and ends_at <= starts_at:
        errors["ends_at"] = "The booking must end after it starts."

    if attendance is None:
        errors["attendance"] = "Enter the expected attendance."
    elif isinstance(attendance, bool) or not isinstance(attendance, int) or attendance < 1:
        errors["attendance"] = "Expected attendance must be a whole number of at least one."

    layout = layout or ""
    if not isinstance(layout, str) or (layout and layout not in RoomLayout.values):
        errors["layout"] = f"Unknown layout. Choose from {', '.join(RoomLayout.labels)}."

    facilities = [] if required_facilities is None else required_facilities
    if not is_facility_list(facilities):
        errors["required_facilities"] = "Required facilities must be a list of names."

    if not isinstance(wheelchair_access_required, bool):
        errors["wheelchair_access_required"] = "Say whether wheelchair access is required."
    if not isinstance(accessibility_notes, str):
        errors["accessibility_notes"] = "Accessibility notes must be text."

    if errors:
        raise BookingValidationError(errors)

    return {
        "event": event,
        "venue": venue,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "attendance": attendance,
        "layout": layout,
        "required_facilities": normalise_facilities(facilities),
        "wheelchair_access_required": wheelchair_access_required,
        "accessibility_notes": accessibility_notes.strip(),
    }


@transaction.atomic
def create_booking_record(*, requested_by, **values) -> VenueBooking:
    """Validate and save a Pending booking with its first history row, together.

    ``requested_by`` must come from the authenticated session, never the payload.
    Callers enforce who may request and whether the venue suits and is free.
    """
    cleaned = validate_booking_request(**values)
    now = timezone.now()
    booking = VenueBooking.objects.create(
        **cleaned,
        status=BookingStatus.PENDING,
        status_changed_at=now,
        requested_by=requested_by,
        requested_at=now,
    )
    VenueBookingHistory.objects.create(
        booking=booking,
        from_status="",
        to_status=BookingStatus.PENDING,
        actor=requested_by,
        changed_at=now,
    )
    return booking


@transaction.atomic
def transition_booking(booking: VenueBooking, target: str, actor, reason: str = "") -> VenueBooking:
    """Move a booking to ``target``, recording who, when and why.

    Raises InvalidBookingTransition for a move the lifecycle does not allow, and
    BookingValidationError for a rejection without a reason. Nothing is saved
    when either is raised.
    """
    locked = VenueBooking.objects.select_for_update().get(pk=booking.pk)
    if target not in ALLOWED_BOOKING_TRANSITIONS.get(locked.status, frozenset()):
        raise InvalidBookingTransition(locked.status, target)
    reason = (reason or "").strip()
    if target == BookingStatus.REJECTED and not reason:
        raise BookingValidationError({"reason": "Enter a reason for the rejection."})

    previous = locked.status
    now = timezone.now()
    locked.status = target
    locked.status_changed_at = now
    fields = ["status", "status_changed_at", "updated_at"]
    if target in (BookingStatus.APPROVED, BookingStatus.REJECTED):
        locked.decided_by = actor
        locked.decided_at = now
        locked.decision_reason = reason
        fields += ["decided_by", "decided_at", "decision_reason"]
    locked.save(update_fields=fields)

    VenueBookingHistory.objects.create(
        booking=locked,
        from_status=previous,
        to_status=target,
        actor=actor,
        reason=reason,
        changed_at=now,
    )
    booking.refresh_from_db()
    return booking
