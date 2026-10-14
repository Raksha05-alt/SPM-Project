"""SCRUM-17 / SCRUM-62 - what a venue's diary looks like over a period.

A period is cut at every point where something changes (opening and closing
time, the edges of a block, a booking or its setup and turnaround) and each
piece gets one status. The strongest reason wins: out of service or outside
operating hours, then a block, then a confirmed booking (with its setup and
turnaround, Week 7 change 1), then a tentative hold that has not expired (Week 7
change 4). A pending request is shown but does not make the venue unavailable.
"""

from datetime import datetime, timedelta
from itertools import pairwise

from django.db import models
from django.utils import timezone

from apps.venues.matching import SINGAPORE
from apps.venues.models import BookingStatus, holding_filter

MAX_RANGE = timedelta(days=31)


class Slot(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    REQUESTED = "REQUESTED", "Requested (not yet reserved)"
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
    """Whether [a, b) lies inside one day's opening hours. Hours must be recorded."""
    local = a.astimezone(SINGAPORE)
    closes = datetime.combine(local.date(), venue.closes_at, tzinfo=SINGAPORE)
    return (
        local.weekday() in venue.operating_days and venue.opens_at <= local.time() and b <= closes
    )


def _occupancy(venue, start, end):
    """Everything that occupies part of the period, as (start, end, slot, detail, event, rank).

    A lower rank wins when two items cover the same moment.
    """
    now = timezone.now()
    items = [
        (b.start, b.end, Slot.BLOCKED, b.reason, None, 0)
        for b in venue.active_blocks().filter(start__lt=end, end__gt=start)
    ]
    setup, turnaround = venue.setup, venue.turnaround
    holding = venue.bookings.filter(
        holding_filter(now),
        start__lt=end + setup + turnaround,
        end__gt=start - setup - turnaround,
    ).select_related("event")
    for b in holding:
        confirmed = b.status == BookingStatus.APPROVED
        slot = Slot.CONFIRMED if confirmed else Slot.TENTATIVE
        if confirmed:
            detail = "Confirmed booking"
        else:
            detail = f"Tentative hold until {timezone.localtime(b.hold_expires_at):%d %b %H:%M}"
        if b.session_name:
            detail = f"{detail} - {b.session_name}"
        core = 1 if confirmed else 3
        items.append((b.start, b.end, slot, detail, b.event, core))
        if setup:
            items.append((b.start - setup, b.start, slot, "Setup", b.event, core + 1))
        if turnaround:
            items.append((b.end, b.end + turnaround, slot, "Turnaround", b.event, core + 1))
    requested = venue.bookings.filter(
        status=BookingStatus.PENDING, start__lt=end, end__gt=start
    ).select_related("event")
    for b in requested:
        items.append(
            (b.start, b.end, Slot.REQUESTED, "Booking request awaiting Venue Staff", b.event, 5)
        )
    return [item for item in items if item[0] < end and item[1] > start]


def segments(venue, start, end) -> list[dict]:
    """The venue's status over ``start``-``end``, as consecutive labelled pieces."""
    items = _occupancy(venue, start, end)
    points = {start, end, *_operating_edges(venue, start, end)}
    for item in items:
        points.update(p for p in item[:2] if start < p < end)

    pieces = []
    for a, b in pairwise(sorted(points)):
        piece = _classify(venue, a, b, items)
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


def _classify(venue, a, b, items) -> dict:
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
    covering = sorted(
        (item for item in items if item[0] < b and item[1] > a), key=lambda item: item[5]
    )
    if covering:
        _, _, slot, detail, event, _ = covering[0]
        if slot in (Slot.BLOCKED, Slot.CONFIRMED, Slot.TENTATIVE):
            return result(slot, detail, event)
    if not _within_hours(venue, a, b):
        return result(Slot.UNAVAILABLE, "Outside operating hours")
    if covering:
        _, _, slot, detail, event, _ = covering[0]
        return result(slot, detail, event)
    return result(Slot.AVAILABLE)


def overall(pieces) -> str:
    """SCRUM-62 - one word for the whole period."""
    # A pending request does not reserve the venue (Week 7 clarification).
    statuses = {
        Slot.AVAILABLE if piece["status"] == Slot.REQUESTED else piece["status"] for piece in pieces
    }
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
