"""SCRUM-11 / 72 / 73 / 67 / 69 - venue booking requests and decisions."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.events.services import notify_status_change, transition_event
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.venues.models import BookingStatus, Venue, VenueBooking
from apps.venues.suitability import assess, unmet

# An event can have venues requested once ConnectSphere has agreed to plan it.
BOOKABLE_EVENT_STATUSES = (EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CONFIRMED)


class BookingRefused(Exception):
    """A booking action that cannot go ahead; ``detail`` says why, ``extra`` adds data."""

    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


class NotAllowed(Exception):
    pass


def venue_staff():
    return User.objects.filter(role=Role.VENUE_STAFF, is_active=True)


def overlapping_blocks(venue, start, end):
    return venue.active_blocks().filter(start__lt=end, end__gt=start)


def clashes(venue_id, start, end, *, event_id):
    """Confirmed bookings of other events at this venue overlapping [start, end).

    Half-open periods: a booking that ends exactly when another starts does not
    clash. Bookings of cancelled events have been released, so they never count.
    """
    return (
        VenueBooking.objects.filter(
            venue_id=venue_id, status=BookingStatus.APPROVED, start__lt=end, end__gt=start
        )
        .exclude(event_id=event_id)
        .exclude(event__status=EventStatus.CANCELLED)
        .select_related("event")
    )


def conflicts_for(booking: VenueBooking):
    """SCRUM-69 - confirmed bookings of other events that overlap this one."""
    return clashes(booking.venue_id, booking.start, booking.end, event_id=booking.event_id)


def _check_bookable(event: EventRequest, user):
    if event.coordinator_id != user.pk:
        raise NotAllowed
    if event.status not in BOOKABLE_EVENT_STATUSES:
        raise BookingRefused(
            f"Venues can be requested once the event is approved; it is {event.get_status_display()}."
        )


def _check_venue(venue: Venue, start, end, needs: dict):
    blocks = list(overlapping_blocks(venue, start, end))
    if blocks:
        raise BookingRefused(
            f"{venue.name} is blocked during this period: {blocks[0].reason}.",
            blocks=[{"start": b.start, "end": b.end, "reason": b.reason} for b in blocks],
        )
    reasons = unmet(assess(venue, needs))
    if reasons:
        raise BookingRefused(
            f"{venue.name} does not meet this event's requirements.", status=400, unmet=reasons
        )


@transaction.atomic
def request_booking(event: EventRequest, user, data: dict) -> VenueBooking:
    """SCRUM-11 - send a booking request to Venue Staff."""
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    _check_bookable(event, user)
    venue = data["venue"]
    needs = {
        "attendance": data["attendance"],
        "layout": data.get("layout", ""),
        "accessibility_needs": data.get("accessibility_needs", ""),
        "facilities": data.get("facilities", []),
        "start": data["start"],
        "end": data["end"],
    }
    _check_venue(venue, data["start"], data["end"], needs)
    booking = VenueBooking.objects.create(event=event, requested_by=user, **data)
    if event.status == EventStatus.APPROVED:
        transition_event(event, EventStatus.PLANNING, user)
        notify_status_change(event, EventStatus.APPROVED, user)
    notify(
        venue_staff(),
        event,
        NotificationKind.BOOKING_REQUESTED,
        f'{user.get_full_name() or user.email} requested {venue.name} for "{event.name}" '
        f"from {timezone.localtime(booking.start):%d %b %Y %H:%M} "
        f"to {timezone.localtime(booking.end):%d %b %Y %H:%M}.",
    )
    return booking


def _locked(booking: VenueBooking) -> VenueBooking:
    return (
        VenueBooking.objects.select_for_update().select_related("event", "venue").get(pk=booking.pk)
    )


def _require_pending(booking: VenueBooking):
    if booking.status != BookingStatus.PENDING:
        raise BookingRefused(
            f"This booking request has already been {booking.get_status_display().lower()}."
        )


def _decided(booking: VenueBooking, user, status: str):
    booking.status = status
    booking.decided_by = user
    booking.decided_at = timezone.now()


@transaction.atomic
def approve_booking(booking: VenueBooking, user) -> VenueBooking:
    """SCRUM-72 AC2 - confirm the venue period; refused while a conflict remains (SCRUM-69)."""
    booking = _locked(booking)
    _require_pending(booking)
    clashes = list(conflicts_for(booking))
    if clashes:
        raise BookingRefused(
            "This request overlaps a confirmed booking and cannot be approved.",
            conflicts=[conflict_row(c) for c in clashes],
        )
    blocks = list(overlapping_blocks(booking.venue, booking.start, booking.end))
    if blocks:
        raise BookingRefused(
            f"{booking.venue.name} is blocked during this period: {blocks[0].reason}."
        )
    _decided(booking, user, BookingStatus.APPROVED)
    booking.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    event = booking.event
    notify(
        [booking.requested_by, event.coordinator],
        event,
        NotificationKind.BOOKING_DECIDED,
        f'{booking.venue.name} is confirmed for "{event.name}" '
        f"({timezone.localtime(booking.start):%d %b %Y %H:%M}).",
    )
    if event.status == EventStatus.CONFIRMED:
        # SCRUM-18 AC1 - a confirmed event's venue changed.
        from apps.events.impact import describe_for_attendees, registered_attendees

        notify(
            registered_attendees(event),
            event,
            NotificationKind.EVENT_CHANGED,
            f'The venue for "{event.name}" has changed. {describe_for_attendees(event)}',
        )
    return booking


@transaction.atomic
def reject_booking(booking: VenueBooking, user, reason: str, suggestion: dict, acknowledge=False):
    """SCRUM-72 AC3 / SCRUM-73 - reject with a reason, optionally suggesting an alternative."""
    booking = _locked(booking)
    _require_pending(booking)
    reason = (reason or "").strip()
    if not reason:
        raise BookingRefused("Enter a reason before rejecting this request.", status=400)
    venue = suggestion.get("suggested_venue")
    start = suggestion.get("suggested_start") or booking.start
    end = suggestion.get("suggested_end") or booking.end
    retimed = bool(suggestion.get("suggested_start") or suggestion.get("suggested_end"))
    if retimed and end <= start:
        raise BookingRefused("The suggested period must end after it starts.", status=400)
    target = venue or (booking.venue if retimed else None)
    if target and not acknowledge:
        # SCRUM-73 AC4 - warn before suggesting a venue that is already taken.
        taken = VenueBooking.objects.filter(
            venue=target, status=BookingStatus.APPROVED, start__lt=end, end__gt=start
        ).exclude(event_id=booking.event_id)
        if taken.exists() or overlapping_blocks(target, start, end).exists():
            raise BookingRefused(
                f"{target.name} is already booked or blocked for that period. "
                "Send the suggestion anyway?",
                warning=True,
            )
    _decided(booking, user, BookingStatus.REJECTED)
    booking.rejection_reason = reason
    booking.suggested_venue = venue
    booking.suggested_start = suggestion.get("suggested_start")
    booking.suggested_end = suggestion.get("suggested_end")
    booking.suggestion_note = (suggestion.get("suggestion_note") or "").strip()
    booking.save()
    event = booking.event
    message = f'{booking.venue.name} cannot be used for "{event.name}". Reason: {reason}'
    alternative = describe_suggestion(booking)
    if alternative:
        message = f"{message} Suggested alternative: {alternative}"
    notify(
        [booking.requested_by, event.coordinator], event, NotificationKind.BOOKING_DECIDED, message
    )
    # SCRUM-58 AC3 - the client hears why an essential arrangement is unavailable.
    notify(
        [event.created_by],
        event,
        NotificationKind.BOOKING_DECIDED,
        f'A requested venue for "{event.name}" is unavailable: {reason} '
        "Your coordinator is arranging an alternative.",
    )
    return booking


def describe_suggestion(booking: VenueBooking) -> str:
    parts = []
    if booking.suggested_venue:
        parts.append(booking.suggested_venue.name)
    if booking.suggested_start and booking.suggested_end:
        parts.append(
            f"{timezone.localtime(booking.suggested_start):%d %b %Y %H:%M} to "
            f"{timezone.localtime(booking.suggested_end):%d %b %Y %H:%M}"
        )
    if booking.suggestion_note:
        parts.append(booking.suggestion_note)
    return ", ".join(parts)


@transaction.atomic
def accept_suggestion(booking: VenueBooking, user) -> VenueBooking:
    """SCRUM-73 AC3 - a new request pre-filled with the suggested venue and timing."""
    booking = _locked(booking)
    if booking.status != BookingStatus.REJECTED or not (
        booking.suggested_venue_id or booking.suggested_start
    ):
        raise BookingRefused("There is no suggested alternative to accept.")
    return request_booking(
        booking.event,
        user,
        {
            "venue": booking.suggested_venue or booking.venue,
            "start": booking.suggested_start or booking.start,
            "end": booking.suggested_end or booking.end,
            "attendance": booking.attendance,
            "layout": booking.layout,
            "facilities": booking.facilities,
            "accessibility_needs": booking.accessibility_needs,
            "notes": booking.notes,
        },
    )


@transaction.atomic
def withdraw_booking(booking: VenueBooking, user, confirm=False) -> VenueBooking:
    """SCRUM-67 - withdraw a request; a confirmed one needs an explicit confirmation."""
    booking = _locked(booking)
    if booking.event.coordinator_id != user.pk:
        raise NotAllowed
    if booking.status not in (BookingStatus.PENDING, BookingStatus.APPROVED):
        raise BookingRefused(
            f"A {booking.get_status_display().lower()} booking cannot be withdrawn."
        )
    if booking.status == BookingStatus.APPROVED and not confirm:
        raise BookingRefused(
            f"{booking.venue.name} is confirmed for this event. Withdrawing releases the "
            "confirmed arrangement. Confirm to continue.",
            warning=True,
        )
    booking.status = BookingStatus.WITHDRAWN
    booking.withdrawn_by = user
    booking.withdrawn_at = timezone.now()
    booking.save(update_fields=["status", "withdrawn_by", "withdrawn_at", "updated_at"])
    notify(
        venue_staff(),
        booking.event,
        NotificationKind.BOOKING_WITHDRAWN,
        f'The request for {booking.venue.name} for "{booking.event.name}" was withdrawn.',
    )
    return booking


def release_for_cancelled_event(event: EventRequest, user) -> None:
    """A cancelled event stops holding any venue (registered as a cancellation hook)."""
    event.venue_bookings.filter(status__in=(BookingStatus.PENDING, BookingStatus.APPROVED)).update(
        status=BookingStatus.RELEASED, updated_at=timezone.now()
    )


def conflict_row(booking: VenueBooking) -> dict:
    return {
        "booking": booking.pk,
        "event": booking.event_id,
        "event_name": booking.event.name,
        "start": booking.start,
        "end": booking.end,
    }


def _period(start, end) -> str:
    return f"{timezone.localtime(start):%d %b %Y %H:%M} to {timezone.localtime(end):%d %b %Y %H:%M}"


@transaction.atomic
def review_booking(
    booking: VenueBooking, user, *, accommodated: bool, note="", start=None, end=None
):
    """SCRUM-80 AC2 / AC3 - Venue Staff record how a flagged booking follows the change."""
    from apps.events.impact import describe_for_attendees, registered_attendees
    from apps.events.models import EventChangeLog

    booking = _locked(booking)
    event = booking.event
    if not booking.review_required:
        raise BookingRefused("This booking does not need review.")
    note = (note or "").strip()
    previous = _period(booking.start, booking.end)
    if accommodated:
        start = start or booking.review_start or booking.start
        end = end or booking.review_end or booking.end
        if end <= start:
            raise BookingRefused("The revised period must end after it starts.", status=400)
        clashing = list(clashes(booking.venue_id, start, end, event_id=booking.event_id))
        if clashing or overlapping_blocks(booking.venue, start, end).exists():
            raise BookingRefused(
                "The revised period is not free at this venue.",
                conflicts=[conflict_row(c) for c in clashing],
            )
        moved = (start, end) != (booking.start, booking.end)
        booking.start, booking.end = start, end
        booking.review_required = False
        booking.review_start = booking.review_end = None
        outcome = f"Revised to {_period(start, end)}." + (f" {note}" if note else "")
    else:
        if not note:
            raise BookingRefused("Explain why the change cannot be accommodated.", status=400)
        moved = False
        outcome = f"Could not accommodate the change: {note}"
    booking.reviewed_by = user
    booking.reviewed_at = timezone.now()
    booking.review_outcome = outcome
    booking.save()
    EventChangeLog.objects.create(
        event=event,
        field=f"Venue booking: {booking.venue.name}"[:60],
        previous_value=previous,
        new_value=outcome,
        changed_by=user,
        significant=True,
    )
    message = f'Venue Staff reviewed {booking.venue.name} for "{event.name}". {outcome}'
    if not accommodated:
        message += (
            " The original booking stays in place until the client and ConnectSphere agree to "
            "keep it, choose another option, or cancel and submit a new request."
        )
    notify([event.created_by, event.coordinator], event, NotificationKind.REVIEW_OUTCOME, message)
    if moved and event.status == EventStatus.CONFIRMED:
        # SCRUM-80 AC4 / SCRUM-18 - registered Attendees hear about the revised arrangement.
        notify(
            registered_attendees(event),
            event,
            NotificationKind.EVENT_CHANGED,
            f'The arrangements for "{event.name}" have changed. {describe_for_attendees(event)}',
        )
    return booking
