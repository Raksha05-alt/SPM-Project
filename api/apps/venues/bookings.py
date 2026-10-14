"""Venue booking requests and decisions.

SCRUM-11 / 72 / 73 / 67 / 69, and the Week 7 customer changes:

1. setup and turnaround time are part of every conflict check (``occupancy``);
2. a venue that becomes unavailable disrupts its bookings without cancelling events;
3. an event may book several venues, each decided independently;
4. Venue Staff may approve a request as a tentative hold that expires.
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.events.services import notify_status_change, transition_event
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.venues import occupancy
from apps.venues.models import LIVE_STATUSES, BookingStatus, Venue, VenueBooking
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


def leads():
    return User.objects.filter(role=Role.COORDINATOR_LEAD, is_active=True)


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


def _period(start, end) -> str:
    return f"{_when(start)} to {_when(end)}"


def _label(booking: VenueBooking) -> str:
    """A booking as people name it: the venue, and the session when there is one."""
    if booking.session_name:
        return f"{booking.venue.name} ({booking.session_name})"
    return booking.venue.name


def overlapping_blocks(venue, start, end):
    """Blocks inside the occupied period of a booking from ``start`` to ``end``."""
    return occupancy.overlapping_blocks(venue, start, end)


def clashes(venue, start, end, *, event_id, exclude_booking_id=None):
    return occupancy.clashes(
        venue, start, end, event_id=event_id, exclude_booking_id=exclude_booking_id
    )


def conflicts_for(booking: VenueBooking):
    """SCRUM-69 - bookings that occupy this venue during this request's occupied period."""
    return clashes(
        booking.venue,
        booking.start,
        booking.end,
        event_id=booking.event_id,
        exclude_booking_id=booking.pk,
    )


def _arrangements_changed(event, user, reason):
    from apps.safety.services import arrangements_changed

    arrangements_changed(event, user, reason)


def _check_bookable(event: EventRequest, user):
    if event.coordinator_id != user.pk:
        raise NotAllowed
    if event.status not in BOOKABLE_EVENT_STATUSES:
        raise BookingRefused(
            f"Venues can be requested once the event is approved; it is {event.get_status_display()}."
        )


def _check_venue(venue: Venue, start, end, needs: dict):
    if not venue.is_active:
        raise BookingRefused(f"{venue.name} is out of service.")
    blocks = list(overlapping_blocks(venue, start, end))
    if blocks:
        raise BookingRefused(
            f"{venue.name} is blocked during this period, including setup and turnaround: "
            f"{blocks[0].reason}.",
            blocks=[{"start": b.start, "end": b.end, "reason": b.reason} for b in blocks],
        )
    reasons = unmet(assess(venue, needs))
    if reasons:
        raise BookingRefused(
            f"{venue.name} does not meet this event's requirements.", status=400, unmet=reasons
        )


@transaction.atomic
def request_booking(event: EventRequest, user, data: dict) -> VenueBooking:
    """SCRUM-11 / Week 7 change 3 - send one venue request to Venue Staff.

    An event can hold several requests (one per venue or session); each one is
    checked on its own against the venue's suitability and availability.
    """
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
    else:
        # Week 7 clarification - a venue added to a planned or confirmed event
        # goes through every approval again; the other venues stay as they are.
        _arrangements_changed(event, user, f"{_label(booking)} was requested.")
    notify(
        venue_staff(),
        event,
        NotificationKind.BOOKING_REQUESTED,
        f'{user.get_full_name() or user.email} requested {_label(booking)} for "{event.name}" '
        f"from {_when(booking.start)} to {_when(booking.end)}.",
    )
    return booking


def _locked(booking: VenueBooking) -> VenueBooking:
    return (
        VenueBooking.objects.select_for_update().select_related("event", "venue").get(pk=booking.pk)
    )


def _lock_venue(venue_id) -> Venue:
    """Serialise decisions at one venue so that two staff cannot both approve
    overlapping requests at the same moment (US-14.1)."""
    return Venue.objects.select_for_update().get(pk=venue_id)


def _require_pending(booking: VenueBooking):
    if booking.status != BookingStatus.PENDING:
        raise BookingRefused(
            f"This booking request has already been {booking.get_status_display().lower()}."
        )


def _decided(booking: VenueBooking, user, status: str):
    booking.status = status
    booking.decided_by = user
    booking.decided_at = timezone.now()


def _check_free(booking: VenueBooking):
    clashing = list(conflicts_for(booking))
    if clashing:
        raise BookingRefused(
            "This request overlaps another booking at this venue, including setup and "
            "turnaround time, and cannot be approved.",
            conflicts=[conflict_row(c) for c in clashing],
        )
    blocks = list(overlapping_blocks(booking.venue, booking.start, booking.end))
    if blocks:
        raise BookingRefused(
            f"{booking.venue.name} is blocked during this period: {blocks[0].reason}."
        )


def _validate_hold(booking: VenueBooking, hold_until):
    if hold_until <= timezone.now():
        raise BookingRefused("The hold must expire in the future.", status=400)
    if hold_until > booking.start:
        raise BookingRefused("The hold must expire before the booking starts.", status=400)


@transaction.atomic
def approve_booking(booking: VenueBooking, user, hold_until=None) -> VenueBooking:
    """SCRUM-72 AC2 / Week 7 change 4 - approve outright, or as a tentative hold.

    A hold reserves the venue until ``hold_until``. The coordinator must confirm
    it before then, or it expires and the venue becomes available again. Refused
    while the request clashes with another booking or a block (SCRUM-69).
    """
    booking = _locked(booking)
    _lock_venue(booking.venue_id)
    _require_pending(booking)
    _check_free(booking)
    event = booking.event
    if hold_until is not None:
        _validate_hold(booking, hold_until)
        _decided(booking, user, BookingStatus.HELD)
        booking.hold_expires_at = hold_until
        booking.hold_set_by = user
        booking.save()
        notify(
            [booking.requested_by, event.coordinator],
            event,
            NotificationKind.BOOKING_DECIDED,
            f'{_label(booking)} is tentatively held for "{event.name}" until '
            f"{_when(hold_until)}. Confirm the hold before then or the venue will be released.",
        )
        return booking
    _decided(booking, user, BookingStatus.APPROVED)
    booking.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    notify(
        [booking.requested_by, event.coordinator],
        event,
        NotificationKind.BOOKING_DECIDED,
        f'{_label(booking)} is confirmed for "{event.name}" ({_when(booking.start)}).',
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
def update_hold(booking: VenueBooking, user, hold_until) -> VenueBooking:
    """Week 7 clarification - Venue Staff set and update how long a hold lasts."""
    booking = _locked(booking)
    if booking.status != BookingStatus.HELD or booking.hold_expired:
        raise BookingRefused("Only a current tentative hold can be changed.")
    _validate_hold(booking, hold_until)
    booking.hold_expires_at = hold_until
    booking.hold_set_by = user
    booking.hold_warning_sent_at = None
    booking.save(
        update_fields=["hold_expires_at", "hold_set_by", "hold_warning_sent_at", "updated_at"]
    )
    event = booking.event
    notify(
        [booking.requested_by, event.coordinator],
        event,
        NotificationKind.BOOKING_DECIDED,
        f'The hold on {_label(booking)} for "{event.name}" now expires {_when(hold_until)}.',
    )
    return booking


@transaction.atomic
def confirm_hold(booking: VenueBooking, user) -> VenueBooking:
    """Week 7 change 4 - the coordinator completes the hold, making it a booking."""
    booking = _locked(booking)
    if booking.event.coordinator_id != user.pk:
        raise NotAllowed
    if booking.status != BookingStatus.HELD:
        raise BookingRefused("Only a tentative hold can be confirmed.")
    if booking.hold_expired:
        # ``process_holds`` records the expiry; here we only refuse.
        raise BookingRefused(
            "This hold has expired and the venue has been released. Request the venue again."
        )
    booking.status = BookingStatus.APPROVED
    booking.hold_confirmed_by = user
    booking.hold_confirmed_at = timezone.now()
    booking.save(update_fields=["status", "hold_confirmed_by", "hold_confirmed_at", "updated_at"])
    notify(
        [booking.hold_set_by or booking.decided_by, *venue_staff()],
        booking.event,
        NotificationKind.BOOKING_DECIDED,
        f'The coordinator confirmed the hold on {_label(booking)} for "{booking.event.name}".',
    )
    return booking


def _expire(booking: VenueBooking) -> None:
    booking.status = BookingStatus.EXPIRED
    booking.expired_at = timezone.now()
    booking.save(update_fields=["status", "expired_at", "updated_at"])
    event = booking.event
    coordinator = event.coordinator
    notify(
        [coordinator or None, booking.requested_by, *([] if coordinator else leads())],
        event,
        NotificationKind.HOLD_EXPIRED,
        f'The tentative hold on {_label(booking)} for "{event.name}" expired at '
        f"{_when(booking.hold_expires_at)}. The venue is no longer reserved for this event.",
    )


def process_holds(now=None) -> dict:
    """Week 7 change 4 - warn coordinators before holds expire, and expire them.

    Idempotent. Runs from the ``process_venue_holds`` management command on a
    schedule, and before any screen that shows bookings, so a hold never outlives
    its deadline even if the schedule is late. (Queries also never treat an
    expired hold as occupying the venue - see ``holding_filter``.)
    """
    now = now or timezone.now()
    warning = timezone.timedelta(hours=getattr(settings, "HOLD_WARNING_HOURS", 24))
    expired = warned = 0
    with transaction.atomic():
        due = (
            VenueBooking.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("event", "venue", "event__coordinator")
            .filter(status=BookingStatus.HELD, hold_expires_at__lte=now)
        )
        for booking in due:
            _expire(booking)
            expired += 1
        soon = (
            VenueBooking.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("event", "venue", "event__coordinator")
            .filter(
                status=BookingStatus.HELD,
                hold_expires_at__gt=now,
                hold_expires_at__lte=now + warning,
                hold_warning_sent_at__isnull=True,
            )
        )
        for booking in soon:
            event = booking.event
            notify(
                [event.coordinator or None, booking.requested_by],
                event,
                NotificationKind.HOLD_EXPIRING,
                f'The tentative hold on {_label(booking)} for "{event.name}" expires '
                f"{_when(booking.hold_expires_at)}. Confirm it before then to keep the venue.",
            )
            booking.hold_warning_sent_at = now
            booking.save(update_fields=["hold_warning_sent_at"])
            warned += 1
    return {"expired": expired, "warned": warned}


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
        taken = clashes(target, start, end, event_id=booking.event_id)
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
    message = f'{_label(booking)} cannot be used for "{event.name}". Reason: {reason}'
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
        parts.append(_period(booking.suggested_start, booking.suggested_end))
    if booking.suggestion_note:
        parts.append(booking.suggestion_note)
    return ", ".join(parts)


def _repeat_of(booking: VenueBooking, **changes) -> dict:
    data = {
        "venue": booking.venue,
        "start": booking.start,
        "end": booking.end,
        "attendance": booking.attendance,
        "session_name": booking.session_name,
        "layout": booking.layout,
        "facilities": booking.facilities,
        "accessibility_needs": booking.accessibility_needs,
        "notes": booking.notes,
    }
    data.update(changes)
    return data


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
        _repeat_of(
            booking,
            venue=booking.suggested_venue or booking.venue,
            start=booking.suggested_start or booking.start,
            end=booking.suggested_end or booking.end,
        ),
    )


WITHDRAWABLE = (*LIVE_STATUSES, BookingStatus.DISRUPTED)


@transaction.atomic
def withdraw_booking(booking: VenueBooking, user, confirm=False) -> VenueBooking:
    """SCRUM-67 / Week 7 change 3 - withdraw one venue; the event's other venues stay.

    A confirmed booking needs an explicit confirmation.
    """
    booking = _locked(booking)
    if booking.event.coordinator_id != user.pk:
        raise NotAllowed
    if booking.status not in WITHDRAWABLE:
        raise BookingRefused(
            f"A {booking.get_status_display().lower()} booking cannot be withdrawn."
        )
    if booking.status == BookingStatus.APPROVED and not confirm:
        raise BookingRefused(
            f"{_label(booking)} is confirmed for this event. Withdrawing releases the "
            "confirmed arrangement; the event's other venues are not affected. Confirm to continue.",
            warning=True,
        )
    was_live = booking.status in (BookingStatus.HELD, BookingStatus.APPROVED)
    booking.status = BookingStatus.WITHDRAWN
    booking.withdrawn_by = user
    booking.withdrawn_at = timezone.now()
    booking.save(update_fields=["status", "withdrawn_by", "withdrawn_at", "updated_at"])
    event = EventRequest.objects.select_for_update().get(pk=booking.event_id)
    if was_live:
        _arrangements_changed(event, user, f"{_label(booking)} was withdrawn.")
    notify(
        venue_staff(),
        event,
        NotificationKind.BOOKING_WITHDRAWN,
        f'The request for {_label(booking)} for "{event.name}" was withdrawn.',
    )
    return booking


@transaction.atomic
def request_replacement(booking: VenueBooking, user, data: dict) -> VenueBooking:
    """Week 7 change 2 - request another venue for a disrupted booking.

    The original booking stays on record as disrupted; the new request carries
    the same session, attendance and needs unless the coordinator changes them.
    """
    booking = _locked(booking)
    if booking.event.coordinator_id != user.pk:
        raise NotAllowed
    if booking.status != BookingStatus.DISRUPTED:
        raise BookingRefused("Only a booking whose venue became unavailable can be replaced.")
    if booking.replaced_by_id:
        raise BookingRefused("A replacement has already been requested for this booking.")
    changes = {key: value for key, value in data.items() if value not in (None, "")}
    replacement = request_booking(booking.event, user, _repeat_of(booking, **changes))
    booking.replaced_by = replacement
    booking.save(update_fields=["replaced_by", "updated_at"])
    return replacement


def release_for_cancelled_event(event: EventRequest, user) -> None:
    """A cancelled event stops holding any venue (registered as a cancellation hook)."""
    event.venue_bookings.filter(status__in=LIVE_STATUSES).update(
        status=BookingStatus.RELEASED, updated_at=timezone.now()
    )


def conflict_row(booking: VenueBooking) -> dict:
    return {
        "booking": booking.pk,
        "event": booking.event_id,
        "event_name": booking.event.name,
        "session_name": booking.session_name,
        "status": booking.status,
        "start": booking.start,
        "end": booking.end,
        "occupied_from": booking.occupied_start,
        "occupied_until": booking.occupied_end,
    }


# --- Week 7 change 2 - a venue becomes unavailable after it was booked -----------


def disrupt_bookings(venue: Venue, user, reason: str, *, start=None, end=None) -> list:
    """Mark every live future booking the unavailability touches as disrupted.

    With ``start``/``end`` (a block) only bookings whose occupied period overlaps
    are affected; without (the venue taken out of service) every future booking
    is. Events are never cancelled: each affected coordinator is told to arrange
    an alternative, the client is told, and a confirmed event returns to planning.
    Call inside a transaction.
    """
    now = timezone.now()
    candidates = (
        venue.bookings.filter(status__in=LIVE_STATUSES, end__gt=now)
        .exclude(event__status__in=(EventStatus.CANCELLED, EventStatus.COMPLETED))
        .select_related("event", "venue", "event__coordinator", "event__created_by")
        .select_for_update(of=("self",))
    )
    affected = []
    for booking in candidates:
        if start is not None and not (
            booking.occupied_start < end and booking.occupied_end > start
        ):
            continue
        booking.status = BookingStatus.DISRUPTED
        booking.disrupted_at = now
        booking.disruption_reason = reason
        booking.save(update_fields=["status", "disrupted_at", "disruption_reason", "updated_at"])
        affected.append(booking)
        event = EventRequest.objects.select_for_update().get(pk=booking.event_id)
        coordinator = event.coordinator
        notify(
            [coordinator] if coordinator else list(leads()),
            event,
            NotificationKind.VENUE_UNAVAILABLE,
            f'{_label(booking)} is no longer available for "{event.name}" '
            f"({_period(booking.start, booking.end)}): {reason} "
            "Alternative arrangements are required; search for and request a replacement venue.",
        )
        notify(
            [event.created_by],
            event,
            NotificationKind.VENUE_UNAVAILABLE,
            f'A venue for "{event.name}" has become unavailable: {reason} Your event is not '
            "cancelled; your coordinator is arranging an alternative.",
        )
        _arrangements_changed(event, user, f"{_label(booking)} became unavailable.")
    return affected


def flag_buffer_conflicts(venue: Venue, user) -> list:
    """Week 7 change 1 - after the setup or turnaround changes, identify the future
    bookings that now clash. They are flagged for Venue Staff review, not removed."""
    flagged = []
    now = timezone.now()
    for booking, rivals in occupancy.problematic_bookings(venue):
        names = ", ".join(f'"{r.event.name}"' for r in rivals)
        booking.review_required = True
        booking.review_reason = (
            f"With setup of {venue.setup_minutes} min and turnaround of "
            f"{venue.turnaround_minutes} min this booking now overlaps {names}."
        )
        booking.review_flagged_at = now
        booking.save(update_fields=["review_required", "review_reason", "review_flagged_at"])
        flagged.append(booking)
        event = booking.event
        notify(
            [*venue_staff(), event.coordinator],
            event,
            NotificationKind.REVIEW_NEEDED,
            f'The booking of {_label(booking)} for "{event.name}" needs review: '
            f"{booking.review_reason}",
        )
        _arrangements_changed(event, user, f"{_label(booking)} needs review.")
    return flagged


@transaction.atomic
def review_booking(
    booking: VenueBooking, user, *, accommodated: bool, note="", start=None, end=None
):
    """SCRUM-80 AC2 / AC3 - Venue Staff record how a flagged booking follows the change."""
    from apps.events.impact import describe_for_attendees, registered_attendees
    from apps.events.models import EventChangeLog

    booking = _locked(booking)
    _lock_venue(booking.venue_id)
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
        clashing = list(
            clashes(
                booking.venue, start, end, event_id=booking.event_id, exclude_booking_id=booking.pk
            )
        )
        if clashing or overlapping_blocks(booking.venue, start, end).exists():
            raise BookingRefused(
                "The revised period is not free at this venue, including setup and turnaround.",
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
    message = f'Venue Staff reviewed {_label(booking)} for "{event.name}". {outcome}'
    if not accommodated:
        message += (
            " The original booking stays in place until the client and ConnectSphere agree to "
            "keep it, choose another option, or cancel and submit a new request."
        )
    notify([event.created_by, event.coordinator], event, NotificationKind.REVIEW_OUTCOME, message)
    attendees = registered_attendees(event) if moved else []
    if attendees:
        # SCRUM-80 AC4 / SCRUM-18 - registered Attendees hear about the revised
        # arrangement, also while a changed event is back in planning (Week 7).
        notify(
            attendees,
            event,
            NotificationKind.EVENT_CHANGED,
            f'The arrangements for "{event.name}" have changed. {describe_for_attendees(event)}',
        )
    return booking
