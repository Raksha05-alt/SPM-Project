"""SCRUM-69: current approved-booking occupancy, using half-open intervals.

Pending requests reserve nothing. Read conflicts afresh rather than persisting a
flag that can become stale after approval, withdrawal or event cancellation.
"""

from datetime import timedelta

from django.db.models import Prefetch

from apps.core.statuses import EventStatus
from apps.venues.models import VenueBooking


def occupying_bookings():
    return VenueBooking.objects.occupying().exclude(event__status=EventStatus.CANCELLED)


def occupancy_prefetch(lookup="bookings"):
    """Request-scoped snapshot for bulk reads; never used for approval writes."""
    return Prefetch(
        lookup,
        queryset=occupying_bookings().order_by("starts_at", "pk"),
        to_attr="occupancy_bookings",
    )


def clashes(venue, starts_at, ends_at, *, exclude_booking_id=None):
    """Return occupying bookings; callers control access to event references.

    Booking IDs and event IDs suffice to identify conflicts without exposing
    private event descriptions, contacts or requirements.
    """
    start, end = effective_interval(venue, starts_at, ends_at)
    # Move the query bounds rather than using database-specific interval arithmetic.
    bookings = (
        occupying_bookings()
        .filter(venue=venue)
        .overlapping(
            start - timedelta(minutes=venue.turnaround_minutes),
            end + timedelta(minutes=venue.setup_minutes),
        )
    )
    if exclude_booking_id is not None:
        bookings = bookings.exclude(pk=exclude_booking_id)
    return bookings.order_by("starts_at", "pk")


def effective_interval(venue, starts_at, ends_at):
    """Canonical half-open venue occupancy; equipment never uses this helper."""
    return (
        starts_at - timedelta(minutes=venue.setup_minutes),
        ends_at + timedelta(minutes=venue.turnaround_minutes),
    )


def booking_reference(venue, booking):
    start, end = effective_interval(venue, booking.starts_at, booking.ends_at)
    return {"id": booking.pk, "event_id": booking.event_id, "starts_at": start, "ends_at": end}


def conflict_references(venue, starts_at, ends_at, *, exclude_booking_id=None):
    return [
        booking_reference(venue, booking)
        for booking in clashes(venue, starts_at, ends_at, exclude_booking_id=exclude_booking_id)
    ]


def booking_review(booking):
    """Fresh flags survive catalogue edits without changing or deleting bookings."""
    from apps.venues.availability import buffer_hours_warning

    conflicts = conflict_references(
        booking.venue, booking.starts_at, booking.ends_at, exclude_booking_id=booking.pk
    )
    warning = buffer_hours_warning(booking.venue, booking.starts_at, booking.ends_at)
    return {
        "occupied_starts_at": effective_interval(booking.venue, booking.starts_at, booking.ends_at)[
            0
        ],
        "occupied_ends_at": effective_interval(booking.venue, booking.starts_at, booking.ends_at)[
            1
        ],
        "conflicts": conflicts,
        "warnings": (
            ["Venue setup/turnaround conflicts with another approved booking."] if conflicts else []
        )
        + ([warning] if warning else []),
    }
