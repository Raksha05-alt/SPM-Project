"""SCRUM-88 staff deadlines, coordinator confirmation, and expiry processing."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.notifications.models import Notification, NotificationKind, NotificationTarget
from apps.notifications.services import notify
from apps.venues.bookings import (
    EVENT_STATUSES_OPEN_TO_REQUESTS,
    BookingValidationError,
    InvalidBookingTransition,
    NotAssignedToEvent,
    VenueNotAvailable,
    _availability_problems,
    _local,
    _lock_for_decision,
    booking_occurrence,
    transition_booking,
)
from apps.venues.models import BookingStatus, VenueBooking, VenueBookingHistory
from apps.venues.suitability import Requirements, ensure_suitable


def validate_hold_deadline(booking, deadline, now):
    if deadline is None or timezone.is_naive(deadline) or not now < deadline < booking.starts_at:
        raise BookingValidationError(
            {"hold_until": "Enter an expiry in the future and before the booking starts."}
        )


def _notice(event, booking, kind, message):
    return notify(
        event=event,
        kind=kind,
        occurrence=booking_occurrence(booking),
        recipients=[event.coordinator_id],
        target_type=NotificationTarget.VENUE_BOOKING,
        target_id=booking.pk,
        message=message,
    )


def _live_hold(event, booking):
    if booking.status != BookingStatus.HELD:
        raise InvalidBookingTransition(booking.status, BookingStatus.APPROVED)
    if event.status not in EVENT_STATUSES_OPEN_TO_REQUESTS or not booking.session.is_active:
        raise BookingValidationError({"event": "This event or session is closed to booking holds."})
    now = timezone.now()
    if not booking.occupies_at(now):
        raise BookingValidationError({"status": "The venue hold has expired."})
    return now


@transaction.atomic
def update_hold_expiry(booking, actor, deadline):
    event, _, locked = _lock_for_decision(booking)
    if actor.role != Role.VENUE_STAFF or not actor.is_active:
        raise BookingValidationError({"event": "Only Venue Staff can change a hold deadline."})
    now = _live_hold(event, locked)
    validate_hold_deadline(locked, deadline, now)
    if locked.hold_until != deadline:
        prior = locked.hold_until
        locked.hold_until = deadline
        locked.save(update_fields=["hold_until", "updated_at"])
        # Each deadline revision has a durable occurrence, including a return
        # to a previously used deadline.
        VenueBookingHistory.objects.create(
            booking=locked,
            from_status=BookingStatus.HELD,
            to_status=BookingStatus.HELD,
            actor=actor,
            changed_at=now,
            reason=f"Hold expiry changed from {_local(prior)} to {_local(deadline)}.",
        )
        _notice(
            event,
            locked,
            NotificationKind.VENUE_HOLD_UPDATED,
            f'The hold on {locked.venue.name} for "{event.name}" now expires at {_local(deadline)}.',
        )
    return locked


@transaction.atomic
def confirm_hold(booking, actor):
    event, venue, locked = _lock_for_decision(booking)
    if (
        actor.role != Role.EVENT_COORDINATOR
        or event.coordinator_id != actor.pk
        or not actor.is_active
    ):
        raise NotAssignedToEvent
    _live_hold(event, locked)
    ensure_suitable(venue, Requirements.for_booking(locked))
    problems = _availability_problems(
        venue, locked.starts_at, locked.ends_at, exclude_booking_id=locked.pk
    )
    if problems:
        raise VenueNotAvailable(problems)
    return transition_booking(locked, BookingStatus.APPROVED, actor, "Coordinator confirmed hold.")


def expire_hold(event, booking):
    """Record expiry and its notice inside the caller's booking transaction."""
    transition_booking(booking, BookingStatus.EXPIRED, None, "Venue hold deadline passed.")
    _notice(
        event,
        booking,
        NotificationKind.VENUE_HOLD_EXPIRED,
        f'The hold on {booking.venue.name} for "{event.name}" has expired. Request a venue again.',
    )


@transaction.atomic
def _process_one_hold(booking, reminder_window):
    event, venue, locked = _lock_for_decision(booking)
    if locked.status != BookingStatus.HELD:
        return 0, 0
    now = timezone.now()
    if locked.hold_until <= now:
        expire_hold(event, locked)
        return 1, 0
    if (
        locked.hold_until <= now + reminder_window
        and event.status in EVENT_STATUSES_OPEN_TO_REQUESTS
    ):
        occurrence = f"{NotificationKind.VENUE_HOLD_REMINDER}:{booking_occurrence(locked)}"
        if Notification.objects.filter(occurrence=occurrence).exists():
            return 0, 0
        reminders = _notice(
            event,
            locked,
            NotificationKind.VENUE_HOLD_REMINDER,
            f'The hold on {venue.name} for "{event.name}" expires at {_local(locked.hold_until)}.',
        )
        return 0, len(reminders)
    return 0, 0


def process_holds():
    """Process due holds with fresh row locks and retry-safe notifications."""
    window = timedelta(hours=settings.VENUE_HOLD_REMINDER_HOURS)
    due = VenueBooking.objects.filter(
        status=BookingStatus.HELD, hold_until__lte=timezone.now() + window
    ).order_by("pk")
    expired = reminded = 0
    for booking in due.iterator():
        expired_now, reminded_now = _process_one_hold(booking, window)
        expired += expired_now
        reminded += reminded_now
    return expired, reminded
