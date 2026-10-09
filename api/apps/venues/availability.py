"""SCRUM-17 / SCRUM-62 - what a venue's diary looks like over a period.

A period is cut at every point where something changes (opening and closing
time, the edges of a block or booking) and each piece gets one status. The
strongest reason wins: out of service or outside operating hours, then a
block, then a confirmed booking, then a tentative hold (a booking request
still waiting for Venue Staff).
"""

from datetime import datetime, timedelta
from itertools import pairwise

from django.db import models

from apps.venues.matching import SINGAPORE
from apps.venues.models import BookingStatus

MAX_RANGE = timedelta(days=31)


class Slot(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    TENTATIVE = "TENTATIVE", "Tentatively held"
    CONFIRMED = "CONFIRMED", "Confirmed booking"
    BLOCKED = "BLOCKED", "Blocked"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"


class InvalidPeriod(ValueError):
    pass


def parse_period(start_value, end_value) -> tuple[datetime, datetime]:
    """Read a ``start``/``end`` pair from a query string; both must carry a timezone."""
    if not start_value or not end_value:
        raise InvalidPeriod("Give both a start and an end.")
    try:
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
    except ValueError as exc:
        raise InvalidPeriod("Dates must be ISO 8601 date-times.") from exc
    if start.utcoffset() is None or end.utcoffset() is None:
        raise InvalidPeriod("Dates must include a timezone.")
    if end <= start:
        raise InvalidPeriod("The end must be after the start.")
    if end - start > MAX_RANGE:
        raise InvalidPeriod("Choose a period of 31 days or less.")
    return start, end


def _operating_edges(venue, start, end):
    if venue.opens_at is None or venue.closes_at is None:
        return []
    edges = []
    day = start.astimezone(SINGAPORE).date()
    last = end.astimezone(SINGAPORE).date()
    while day <= last:
        for moment in (venue.opens_at, venue.closes_at):
            edge = datetime.combine(day, moment, tzinfo=SINGAPORE)
            if start < edge < end:
                edges.append(edge)
        day += timedelta(days=1)
    return edges


def _within_hours(venue, a, b) -> bool:
    if venue.opens_at is None or venue.closes_at is None:
        return False
    local = a.astimezone(SINGAPORE)
    closes = datetime.combine(local.date(), venue.closes_at, tzinfo=SINGAPORE)
    return (
        local.weekday() in venue.operating_days and venue.opens_at <= local.time() and b <= closes
    )


def segments(venue, start, end) -> list[dict]:
    """The venue's status over ``start``-``end``, as consecutive labelled pieces."""
    blocks = list(venue.active_blocks().filter(start__lt=end, end__gt=start))
    bookings = list(
        venue.bookings.filter(
            status__in=(BookingStatus.PENDING, BookingStatus.APPROVED),
            start__lt=end,
            end__gt=start,
        ).select_related("event")
    )
    points = {start, end, *_operating_edges(venue, start, end)}
    for item in [*blocks, *bookings]:
        points.update(p for p in (item.start, item.end) if start < p < end)

    pieces = []
    for a, b in pairwise(sorted(points)):
        piece = _classify(venue, a, b, blocks, bookings)
        previous = pieces[-1] if pieces else None
        if previous and (previous["status"], previous["detail"], previous["event"]) == (
            piece["status"],
            piece["detail"],
            piece["event"],
        ):
            previous["end"] = b
        else:
            pieces.append({"start": a, "end": b, **piece})
    return pieces


def _classify(venue, a, b, blocks, bookings) -> dict:
    def result(slot, detail="", event=None):
        return {
            "status": slot.value,
            "label": slot.label,
            "detail": detail,
            "event": event.pk if event else None,
            "event_name": event.name if event else None,
        }

    if not venue.is_active:
        return result(Slot.UNAVAILABLE, "Venue is out of service")
    if venue.opens_at is None or venue.closes_at is None:
        return result(Slot.UNAVAILABLE, "Operating hours have not been recorded")
    if not _within_hours(venue, a, b):
        return result(Slot.UNAVAILABLE, "Outside operating hours")
    for block in blocks:
        if block.start < b and block.end > a:
            return result(Slot.BLOCKED, block.reason)
    held = [booking for booking in bookings if booking.start < b and booking.end > a]
    for booking in held:
        if booking.status == BookingStatus.APPROVED:
            return result(Slot.CONFIRMED, "Confirmed booking", booking.event)
    if held:
        return result(Slot.TENTATIVE, "Booking request awaiting Venue Staff", held[0].event)
    return result(Slot.AVAILABLE)


def overall(pieces) -> str:
    """SCRUM-62 - one word for the whole period."""
    statuses = {piece["status"] for piece in pieces}
    if statuses == {Slot.AVAILABLE}:
        return "AVAILABLE"
    if statuses == {Slot.BLOCKED}:
        return "BLOCKED"
    if Slot.AVAILABLE in statuses:
        return "PARTIAL"
    return "UNAVAILABLE"


OVERALL_LABELS = {
    "AVAILABLE": "Available for the whole period",
    "PARTIAL": "Partly available",
    "BLOCKED": "Blocked for the whole period",
    "UNAVAILABLE": "Not available",
}
