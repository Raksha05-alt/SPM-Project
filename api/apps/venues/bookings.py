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
booking rows. A move into or out of Approved calls
``apps.safety.services.arrangements_changed`` (SCRUM-90), so callers should
already hold the event row lock.
"""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import NotificationKind, NotificationTarget
from apps.notifications.services import notify
from apps.venues.layouts import LayoutChoiceError, check_choice, claim_layouts
from apps.venues.models import BookingStatus, Venue, VenueBooking, VenueBookingHistory
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
    if not isinstance(layout, str):
        errors["layout"] = "Choose a layout from the catalogue."
    elif layout:
        # SCRUM-91 AC4 - a retired or unknown layout cannot be chosen.
        try:
            check_choice([layout])
        except LayoutChoiceError as exc:
            errors["layout"] = exc.message

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
    if cleaned["layout"]:
        try:
            claim_layouts([cleaned["layout"]])
        except LayoutChoiceError as exc:
            raise BookingValidationError({"layout": exc.message}) from None
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
    # Serialize approvals of different requests for the same venue. Lock the
    # event before the venue and booking, following the shared resource order.
    from apps.events.models import EventRequest

    identity = VenueBooking.objects.values("event_id", "venue_id").get(pk=booking.pk)
    event = EventRequest.objects.select_for_update().get(pk=identity["event_id"])
    venue = Venue.objects.select_for_update().get(pk=identity["venue_id"])
    locked = VenueBooking.objects.select_for_update().get(pk=booking.pk)
    if target not in ALLOWED_BOOKING_TRANSITIONS.get(locked.status, frozenset()):
        raise InvalidBookingTransition(locked.status, target)
    reason = (reason or "").strip()
    if target == BookingStatus.REJECTED and not reason:
        raise BookingValidationError({"reason": "Enter a reason for the rejection."})

    if target == BookingStatus.APPROVED:
        from apps.venues.occupancy import conflict_references

        if event.status in EVENT_STATUSES_CLOSED_TO_BOOKING:
            raise BookingValidationError({"event": "This event cannot receive a venue approval."})
        conflicts = conflict_references(venue, locked.starts_at, locked.ends_at)
        if conflicts:
            references = ", ".join(str(item["event_id"]) for item in conflicts)
            raise BookingValidationError(
                {"venue": f"The venue conflicts with event(s): {references}."}
            )

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
    if BookingStatus.APPROVED in (previous, target):
        # SCRUM-90 AC6 - a venue is added to or removed from the event's
        # arrangements, so any safety check no longer describes it.
        from apps.safety.services import arrangements_changed

        arrangements_changed(
            locked.event,
            f"The booking for {locked.venue.name} is now {BookingStatus(target).label.lower()}.",
            actor,
        )
    booking.refresh_from_db()
    return booking


# SCRUM-11 - a venue is requested once the event has been approved for planning.
# The first request on an Approved event moves it to Planning in the same
# transaction (the "start planning" step in the Sprint 3 guide, gate G09).
EVENT_STATUSES_OPEN_TO_REQUESTS = frozenset({EventStatus.APPROVED, EventStatus.PLANNING})


class NotAssignedToEvent(Exception):
    """SCRUM-11 AC6 - only the event's assigned coordinator may request a venue."""


class VenueNotAvailable(Exception):
    """The venue is blocked, out of service or already approved for that period."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(" ".join(reasons))


def _local(moment) -> str:
    """A stored instant as Singapore time for messages people read."""
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


def _availability_problems(venue, starts_at, ends_at) -> list[str]:
    from apps.venues.availability import availability

    period = availability(venue, starts_at, ends_at)
    problems = [
        f"The venue is blocked from {_local(b['starts_at'])} to "
        f"{_local(b['ends_at'])}: {b['reason']}"
        for b in period["blocks"]
    ]
    if not venue.in_service:
        problems.append("The venue is out of service.")
    if period["conflicts"]:
        events = ", ".join(str(c["event_id"]) for c in period["conflicts"])
        problems.append(f"The venue is already approved for event(s) {events} in this period.")
    return problems


@transaction.atomic
def request_booking(*, event, venue, requested_by, **values) -> VenueBooking:
    """SCRUM-11 - the assigned coordinator requests a venue for their event.

    Locks the event, then the venue (the shared lock order), and refuses, with
    nothing saved, when the user is not the assigned coordinator (AC6), the
    request is incomplete or invalid (AC3, every item named), the venue does not
    suit the event (SCRUM-71 AC4, every unmet requirement named) or it is
    blocked, out of service or already approved for that period. On success it
    saves a Pending booking, starts planning an Approved event and notifies
    Venue Staff (AC4).
    """
    from apps.accounts.models import Role, User
    from apps.events.models import EventRequest
    from apps.events.services import transition_event
    from apps.venues.suitability import Requirements, ensure_suitable

    locked_event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked_event.coordinator_id is None or locked_event.coordinator_id != requested_by.pk:
        raise NotAssignedToEvent
    if locked_event.status not in EVENT_STATUSES_OPEN_TO_REQUESTS:
        raise BookingValidationError(
            {
                "event": (
                    "A venue can be requested once the event is approved; "
                    f"this event is {locked_event.get_status_display()}."
                )
            }
        )
    locked_venue = Venue.objects.select_for_update().get(pk=venue.pk) if venue is not None else None
    cleaned = validate_booking_request(event=locked_event, venue=locked_venue, **values)

    # SCRUM-71 AC4 - raises VenueUnsuitable with every unmet requirement.
    ensure_suitable(locked_venue, Requirements.for_booking(_Requested(**cleaned)))
    problems = _availability_problems(locked_venue, cleaned["starts_at"], cleaned["ends_at"])
    if problems:
        raise VenueNotAvailable(problems)

    if locked_event.status == EventStatus.APPROVED:
        transition_event(locked_event, EventStatus.PLANNING, requested_by)

    values = {key: value for key, value in cleaned.items() if key not in ("event", "venue")}
    booking = create_booking_record(
        requested_by=requested_by, event=locked_event, venue=locked_venue, **values
    )
    staff = User.objects.filter(role=Role.VENUE_STAFF, is_active=True)
    name = requested_by.get_full_name() or requested_by.email
    notify(
        event=locked_event,
        kind=NotificationKind.VENUE_REQUESTED,
        occurrence=booking_occurrence(booking),
        recipients=staff,
        target_type=NotificationTarget.VENUE_BOOKING,
        target_id=booking.pk,
        message=(
            f'{name} requested {locked_venue.name} for "{locked_event.name}" '
            f"({_local(booking.starts_at)} to {_local(booking.ends_at)}). "
            "Review it in Booking requests."
        ),
    )
    return booking


class _Requested:
    """The cleaned request values, shaped like a booking for ``Requirements.for_booking``."""

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


@transaction.atomic
def withdraw_booking(*, booking, actor, expected_status, confirm_release=False):
    """SCRUM-67: withdraw under the shared resource locks, with durable staff notices."""
    from apps.accounts.models import Role, User
    from apps.events.models import EventRequest

    identity = VenueBooking.objects.values("event_id", "venue_id").get(pk=booking.pk)
    event = EventRequest.objects.select_for_update().get(pk=identity["event_id"])
    Venue.objects.select_for_update().get(pk=identity["venue_id"])
    locked = VenueBooking.objects.select_for_update().get(pk=booking.pk)
    if actor.role != Role.EVENT_COORDINATOR or event.coordinator_id != actor.pk:
        raise NotAssignedToEvent
    if event.status in EVENT_STATUSES_CLOSED_TO_BOOKING:
        raise BookingValidationError({"event": "This event is closed to booking withdrawals."})
    if locked.status != expected_status:
        raise BookingValidationError(
            {"status": "The booking has changed. Reload before withdrawing."}
        )
    if locked.status == BookingStatus.APPROVED and confirm_release is not True:
        raise BookingValidationError(
            {"confirm_release": "This releases a confirmed venue arrangement. Confirm to continue."}
        )
    transition_booking(locked, BookingStatus.WITHDRAWN, actor)
    notify(
        event=event,
        kind=NotificationKind.VENUE_WITHDRAWN,
        occurrence=booking_occurrence(locked),
        recipients=User.objects.filter(role=Role.VENUE_STAFF, is_active=True),
        target_type=NotificationTarget.VENUE_BOOKING,
        target_id=locked.pk,
        message=(
            f"{actor.get_full_name() or actor.email} withdrew the booking "
            f'for {locked.venue.name} for "{event.name}" '
            f"({_local(locked.starts_at)} to {_local(locked.ends_at)})."
        ),
    )
    return locked


# SCRUM-72 - Venue Staff record their decision on a Pending booking request.


def _lock_for_decision(booking):
    """Lock the event, venue and booking rows in the shared order and return them."""
    from apps.events.models import EventRequest

    identity = VenueBooking.objects.values("event_id", "venue_id").get(pk=booking.pk)
    event = EventRequest.objects.select_for_update().get(pk=identity["event_id"])
    venue = Venue.objects.select_for_update().get(pk=identity["venue_id"])
    locked = VenueBooking.objects.select_for_update().get(pk=booking.pk)
    return event, venue, locked


def booking_occurrence(booking) -> str:
    """The occurrence of the booking's latest status change (one history row each)."""
    latest = booking.history.order_by("-pk").values_list("pk", flat=True).first()
    return f"booking-status:{latest}"


def _notify_coordinator(event, booking, message) -> None:
    """SCRUM-79 AC3 - tell the event's current coordinator (or, failing that, the requester)."""
    notify(
        event=event,
        kind=NotificationKind.VENUE_DECIDED,
        occurrence=booking_occurrence(booking),
        recipients=[event.coordinator_id or booking.requested_by_id],
        target_type=NotificationTarget.VENUE_BOOKING,
        target_id=booking.pk,
        message=message,
    )


@transaction.atomic
def approve_booking(booking: VenueBooking, actor) -> VenueBooking:
    """SCRUM-72 AC2/AC5/AC6 - approve a Pending request and notify the coordinator.

    Rechecks, under the event/venue/booking locks, that the request is still
    Pending (AC5), the venue still suits it (SCRUM-71), is in service, unblocked
    and free (SCRUM-69), and the event has no other approved venue. Any failure
    raises with nothing saved; an earlier successful search does not count.
    """
    from apps.venues.suitability import Requirements, ensure_suitable

    event, venue, locked = _lock_for_decision(booking)
    if locked.status != BookingStatus.PENDING:
        raise InvalidBookingTransition(locked.status, BookingStatus.APPROVED)
    if event.status in EVENT_STATUSES_CLOSED_TO_BOOKING:
        raise BookingValidationError({"event": "This event cannot receive a venue approval."})
    if VenueBooking.objects.filter(event=event, status=BookingStatus.APPROVED).exists():
        raise BookingValidationError(
            {"event": "This event already has an approved venue. Withdraw it first."}
        )
    # SCRUM-71 - raises VenueUnsuitable with every unmet requirement.
    ensure_suitable(venue, Requirements.for_booking(locked))
    problems = _availability_problems(venue, locked.starts_at, locked.ends_at)
    if problems:
        raise VenueNotAvailable(problems)

    transition_booking(locked, BookingStatus.APPROVED, actor)
    locked.refresh_from_db()
    _notify_coordinator(
        event,
        locked,
        f'Venue Staff approved {venue.name} for "{event.name}" '
        f"({_local(locked.starts_at)} to {_local(locked.ends_at)}).",
    )
    return locked


@transaction.atomic
def reject_booking(booking: VenueBooking, actor, reason: str) -> VenueBooking:
    """SCRUM-72 AC3-AC6 - reject a Pending request with a reason and notify the coordinator.

    A blank reason (AC4) or an already-decided request (AC5) raises with nothing saved.
    SCRUM-58 AC3 - the venue is unavailable, so the Event Organiser also receives the reason.
    """
    from apps.events.confirmation import notify_unavailable

    event, venue, locked = _lock_for_decision(booking)
    transition_booking(locked, BookingStatus.REJECTED, actor, reason)
    locked.refresh_from_db()
    _notify_coordinator(
        event,
        locked,
        f'Venue Staff rejected {venue.name} for "{event.name}" '
        f"({_local(locked.starts_at)} to {_local(locked.ends_at)}). "
        f"Reason: {locked.decision_reason}",
    )
    notify_unavailable(
        event,
        f'{venue.name} is unavailable for "{event.name}", so the event is not confirmed. '
        f"Reason: {locked.decision_reason}",
        occurrence=booking_occurrence(locked),
    )
    return locked
