"""SCRUM-69: current approved-booking occupancy, using half-open intervals.

Pending requests reserve nothing. Read conflicts afresh rather than persisting a
flag that can become stale after approval, withdrawal or event cancellation.
"""

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
    bookings = occupying_bookings().filter(venue=venue).overlapping(starts_at, ends_at)
    if exclude_booking_id is not None:
        bookings = bookings.exclude(pk=exclude_booking_id)
    return bookings.order_by("starts_at", "pk")


def conflict_references(venue, starts_at, ends_at, *, exclude_booking_id=None):
    return list(
        clashes(venue, starts_at, ends_at, exclude_booking_id=exclude_booking_id).values(
            "id", "event_id", "starts_at", "ends_at"
        )
    )
