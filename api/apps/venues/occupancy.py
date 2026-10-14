"""Week 7 change 1 - when a venue is actually occupied, including setup and turnaround.

A booking from 10:00 to 12:00 at a venue with 30 minutes of setup and 45 minutes
of turnaround occupies the venue from 09:30 to 12:45. Every availability check
and conflict check in the system goes through this module so the rule lives in
one place.

Two bookings of *different* events at the same venue clash when their occupied
periods overlap. With setup ``s`` and turnaround ``t`` that is the same as their
published periods being less than ``s + t`` apart: the room needs resetting
after the first and preparing before the second. Periods are half-open, so a
gap of exactly ``s + t`` is fine.

Two bookings of the *same* event at the same venue (two sessions in one room)
clash only if the sessions themselves overlap: the room stays set up between
them.

A block (Week 7 change 2) is a raw period in which the venue cannot be used, so a
booking clashes with it when the booking's occupied period touches it.

A pending request does not occupy anything (Week 7 clarification); a tentative
hold does until it expires; an approved booking does.
"""

from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.venues.models import BookingStatus, VenueBooking, holding_filter


def gap(venue) -> timezone.timedelta:
    return venue.setup + venue.turnaround


def occupied_period(venue, start, end):
    return start - venue.setup, end + venue.turnaround


def clashes(venue, start, end, *, event_id=None, exclude_booking_id=None, now=None):
    """Bookings that occupy ``venue`` too close to, or during, ``start``-``end``."""
    now = now or timezone.now()
    room = gap(venue)
    holding = (
        VenueBooking.objects.filter(holding_filter(now), venue=venue)
        .exclude(event__status=EventStatus.CANCELLED)
        .select_related("event", "venue")
    )
    others = holding.filter(start__lt=end + room, end__gt=start - room)
    if event_id is not None:
        others = others.exclude(event_id=event_id)
        same_event = holding.filter(event_id=event_id, start__lt=end, end__gt=start)
        others = others | same_event
    if exclude_booking_id is not None:
        others = others.exclude(pk=exclude_booking_id)
    return others.order_by("start", "pk")


def overlapping_blocks(venue, start, end):
    """Active blocks that fall inside the booking's occupied period."""
    occupied_start, occupied_end = occupied_period(venue, start, end)
    return venue.active_blocks().filter(start__lt=occupied_end, end__gt=occupied_start)


def exclusion_windows(venue, *, exclude_event_id=None, now=None):
    """Periods in which a new booking's *published* time may not fall at this venue.

    Used by venue search and the shortlist, which compare a requested period with
    a list of periods. Bookings are widened by setup + turnaround on both sides;
    blocks by turnaround before and setup after.
    """
    now = now or timezone.now()
    room = gap(venue)
    bookings = venue.bookings.filter(holding_filter(now)).exclude(
        event__status=EventStatus.CANCELLED
    )
    if exclude_event_id:
        bookings = bookings.exclude(event_id=exclude_event_id)
    windows = [(b.start - room, b.end + room) for b in bookings]
    windows += [(b.start - venue.turnaround, b.end + venue.setup) for b in venue.active_blocks()]
    return windows


def problematic_bookings(venue, *, now=None):
    """Future bookings at ``venue`` that clash under its current setup and turnaround.

    Used when Venue Staff change the buffers: the bookings are identified, never
    removed (Week 7 change 1).
    """
    now = now or timezone.now()
    live = list(
        venue.bookings.filter(holding_filter(now), end__gt=now)
        .exclude(event__status=EventStatus.CANCELLED)
        .select_related("event", "venue")
        .order_by("start", "pk")
    )
    found = {}
    for booking in live:
        rivals = list(
            clashes(
                venue,
                booking.start,
                booking.end,
                event_id=booking.event_id,
                exclude_booking_id=booking.pk,
                now=now,
            )
        )
        if rivals:
            found[booking.pk] = (booking, rivals)
    return list(found.values())


LIVE_FOR_DISRUPTION = (BookingStatus.PENDING, BookingStatus.HELD, BookingStatus.APPROVED)
