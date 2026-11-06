"""SCRUM-70 proposed-period provider for ASSESS/APPLY.

Preview is read-only. The writer must run inside APPLY's transaction, after
its source/permission checks and before changing the event fields. It locks
this event then venues, and always reassesses live occupancy, never a preview.
It does not apply event changes, move bookings or invent staff approval.
"""

from datetime import datetime

from django.db import connection
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.statuses import EventStatus
from apps.events.history import jsonable
from apps.events.models import (
    ChangeRequestStatus,
    EventChangeRequest,
    EventRequest,
    VenuePeriodReview,
)
from apps.venues.models import BookingStatus, Venue
from apps.venues.occupancy import conflict_references


def _datetime(value):
    result = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or timezone.is_naive(result):
        raise ValueError("An aware date and time is required.")
    return result


def shifted(booking, event, proposed):
    """Translate a session by the event start delta; extend only its main end.

    Breakout durations remain independent. Explicit target booking IDs select
    affected sessions; an empty target list means all approved sessions.
    """
    old_start = _datetime(event.preferred_start)
    old_end = _datetime(event.preferred_end)
    start = _datetime(proposed.get("preferred_start", old_start))
    end = _datetime(proposed.get("preferred_end", old_end))
    delta = start - old_start
    new_start = booking.starts_at + delta
    new_end = booking.ends_at + delta
    if booking.session.kind == "MAIN":
        new_end += (end - start) - (old_end - old_start)
    if new_end <= new_start:
        raise ValueError("The proposed booking must end after it starts.")
    return new_start, new_end


def venue_conflicts(event, proposed, *, target_bookings=None):
    """Pure preview: original booking/occupancy is never altered.

    Returns clear assessments too: those still require a real Venue Staff
    decision under APPLY. Unchanged sessions are omitted.
    """
    if not {"preferred_start", "preferred_end"}.intersection(proposed):
        return []
    bookings = event.venue_bookings.filter(status=BookingStatus.APPROVED)
    if target_bookings:
        if set(target_bookings) - set(bookings.values_list("pk", flat=True)):
            raise ValueError("Target bookings must be this event's approved bookings.")
        bookings = bookings.filter(pk__in=target_bookings)
    results = []
    for booking in bookings.select_related("venue", "session").order_by("pk"):
        start, end = shifted(booking, event, proposed)
        if (start, end) == (booking.starts_at, booking.ends_at):
            continue
        conflicts = conflict_references(booking.venue, start, end, exclude_booking_id=booking.pk)
        results.append(
            {
                "booking": booking.pk,
                "venue": booking.venue.name,
                "starts_at": start,
                "ends_at": end,
                "conflicts": conflicts,
                "needs_staff_review": True,
            }
        )
    return results


def record_period_reviews(change_request, actor):
    """APPLY callback: persist fresh assessments without releasing originals.

    Caller owns the outer atomic transaction and checks source freshness before
    editing event fields. Replay returns the same immutable revision records.
    This provider never imports or invokes the APPLY workflow.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("Period reviews require the applying action's transaction.")
    event = EventRequest.objects.select_for_update().get(pk=change_request.event_id)
    change = EventChangeRequest.objects.get(pk=change_request.pk)
    if change.status != ChangeRequestStatus.APPROVED or change.revision != change_request.revision:
        raise ValueError("An approved, current change request is required.")
    if change.source_status != EventStatus.CONFIRMED:
        raise ValueError("This provider handles changes requested for confirmed events.")
    if not actor.is_active or event.coordinator_id != actor.pk or not actor.is_coordinator:
        raise PermissionError("Only the active assigned coordinator may record this change.")
    from apps.events.change_requests import source_snapshot

    if source_snapshot(event)[1] != change.source_digest:
        raise ValueError("The event changed since this proposal was requested.")
    venue_ids = event.venue_bookings.filter(status=BookingStatus.APPROVED).values_list(
        "venue_id", flat=True
    )
    list(Venue.objects.select_for_update().filter(pk__in=venue_ids).order_by("pk"))
    reviews = []
    for assessment in venue_conflicts(
        event, change.proposed_values, target_bookings=change.target_bookings
    ):
        review, created = VenuePeriodReview.objects.get_or_create(
            booking_id=assessment["booking"],
            change_request=change,
            revision=change.revision,
            defaults={
                "starts_at": assessment["starts_at"],
                "ends_at": assessment["ends_at"],
                "conflicts": [
                    {k: jsonable(v) for k, v in c.items()} for c in assessment["conflicts"]
                ],
                "raised_by": actor,
            },
        )
        if created:
            from apps.notifications.models import NotificationKind, NotificationTarget
            from apps.notifications.services import notify

            notify(
                event=event,
                kind=NotificationKind.VENUE_REVIEW,
                occurrence=f"venue-period-review:{review.pk}",
                recipients=[event.coordinator_id],
                target_type=NotificationTarget.VENUE_BOOKING,
                target_id=review.booking_id,
                message=f"{assessment['venue']} requires staff review of the proposed period "
                f'for "{event.name}". The current booking is retained.',
            )
        reviews.append(review)
    return reviews


def review_period(review, actor, *, reason):
    """Staff-outcome callback for APPLY, rechecking occupancy under the venue lock.

    A recorded clear result does not move a booking or promise availability at
    future application. APPLY must revalidate before an atomic resource switch.
    """
    from django.db import transaction

    from apps.accounts.models import Role
    from apps.venues.models import VenueBooking

    if not actor.is_active or actor.role != Role.VENUE_STAFF:
        raise PermissionError("Only active Venue Staff may review the proposed period.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Record a reason for the staff review.")
    with transaction.atomic():
        EventRequest.objects.select_for_update().get(pk=review.booking.event_id)
        Venue.objects.select_for_update().get(pk=review.booking.venue_id)
        current = (
            VenuePeriodReview.objects.select_for_update()
            .select_related("booking__venue", "change_request")
            .get(pk=review.pk)
        )
        if current.reviewed_at is not None:
            raise ValueError("This review already has a staff decision.")
        if (
            current.change_request.revision != current.revision
            or current.change_request.status
            not in (
                ChangeRequestStatus.APPROVED,
                # SCRUM-80 - APPLY records staff outcomes while the change is in review.
                ChangeRequestStatus.IN_REVIEW,
            )
        ):
            raise ValueError("This period review has been superseded.")
        booking = VenueBooking.objects.get(pk=current.booking_id)
        if booking.status != BookingStatus.APPROVED:
            raise ValueError("The original booking is no longer approved.")
        conflicts = conflict_references(
            booking.venue, current.starts_at, current.ends_at, exclude_booking_id=booking.pk
        )
        current.conflicts = [{k: jsonable(v) for k, v in c.items()} for c in conflicts]
        current.reviewed_by = actor
        current.reviewed_at = timezone.now()
        current.review_reason = reason.strip()
        current.save(update_fields=["conflicts", "reviewed_by", "reviewed_at", "review_reason"])
        return current
