"""SCRUM-17: fresh availability, using Singapore operating hours.

Intervals are half-open: a block ending at 10:00 does not obstruct a 10:00 start.
Missing operating hours are unavailable rather than assumed to be open.
Approved bookings occupy their setup, event and turnaround period.
"""

from datetime import datetime, timedelta

from django.utils import timezone

from apps.venues.occupancy import booking_reference, conflict_references, effective_interval

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def operating_hours_problem(venue, start, end) -> str | None:
    """Why ``[start, end)`` is outside the venue's operating hours, or None if it fits.

    The one operating-hours rule, shared by availability, discovery and the
    SCRUM-71 suitability assessment. Times are compared in Singapore time;
    starting exactly at opening and ending exactly at closing fits.
    """
    if not venue.opens_at or not venue.closes_at or not venue.operating_days:
        return (
            "The venue's operating hours are not recorded, so the event timing cannot be confirmed."
        )
    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    hours = f"{venue.opens_at:%H:%M}-{venue.closes_at:%H:%M}"
    if local_end <= local_start:
        return "The event ends before it starts."
    if local_start.weekday() not in venue.operating_days:
        return f"The event falls on a {DAY_NAMES[local_start.weekday()]}, when the venue is closed."
    # The venue contract has same-day opening/closing hours. A continuous
    # interval spanning nights necessarily includes closed time.
    if local_start.date() != local_end.date():
        return f"The event runs overnight, outside the venue's operating hours of {hours}."
    if local_start.time() < venue.opens_at or local_end.time() > venue.closes_at:
        return (
            f"The event runs {_clock(local_start)}-{_clock(local_end)}, outside the venue's "
            f"operating hours of {hours}."
        )
    return None


def _clock(moment) -> str:
    # Show seconds only when they matter, so 22:00:01 is not reported as 22:00.
    return f"{moment:%H:%M:%S}" if moment.second else f"{moment:%H:%M}"


def within_operating_hours(venue, start, end):
    return operating_hours_problem(venue, start, end) is None


def buffer_hours_warning(venue, start, end):
    if operating_hours_problem(venue, start, end):
        return None
    occupied_start, occupied_end = effective_interval(venue, start, end)
    if operating_hours_problem(venue, occupied_start, occupied_end):
        return "Setup or turnaround extends outside operating hours. Venue Staff may still approve."
    return None


def availability(venue, start, end):
    occupied_start, occupied_end = effective_interval(venue, start, end)
    # Discovery checks several venues at once. Reuse its request-scoped prefetch
    # without changing the same half-open overlap rule used by direct checks.
    if "blocks" in getattr(venue, "_prefetched_objects_cache", {}):
        blocks = [
            b
            for b in venue.blocks.all()
            if b.starts_at < occupied_end and b.ends_at > occupied_start
        ]
    else:
        blocks = list(venue.blocks.filter(starts_at__lt=occupied_end, ends_at__gt=occupied_start))
    if hasattr(venue, "occupancy_bookings"):
        instant = timezone.now()
        conflicts = [
            booking_reference(venue, b)
            for b in venue.occupancy_bookings
            if b.occupies_at(instant)
            and effective_interval(venue, b.starts_at, b.ends_at)[0] < occupied_end
            and effective_interval(venue, b.starts_at, b.ends_at)[1] > occupied_start
        ]
    else:
        conflicts = conflict_references(venue, start, end)
    if blocks:
        status = "blocked"
    elif conflicts:
        status = "booked"
    elif not venue.in_service or not within_operating_hours(venue, start, end):
        status = "unavailable"
    else:
        status = "available"
    return {
        "warnings": [w] if (w := buffer_hours_warning(venue, start, end)) else [],
        "venue_id": venue.pk,
        "starts_at": start,
        "ends_at": end,
        "timezone": timezone.get_default_timezone_name(),
        "status": status,
        "available": status == "available",
        "conflicts": conflicts,
        "blocks": [
            {"id": b.pk, "reason": b.reason, "starts_at": b.starts_at, "ends_at": b.ends_at}
            for b in blocks
        ],
    }


def comparison_availability(venue, start, end):
    """Subtract the union of current obstructions from recorded opening windows.

    Return timing and generic reasons only: comparison never discloses another
    event's identity, private requirements or staff-entered block notes.
    """
    current = availability(venue, start, end)
    occupied = sorted(
        (
            max(start, item["starts_at"] - timedelta(minutes=venue.turnaround_minutes)),
            min(end, item["ends_at"] + timedelta(minutes=venue.setup_minutes)),
        )
        for item in current["blocks"] + current["conflicts"]
    )
    free = []
    reasons = []
    if not venue.in_service:
        reasons.append("Venue is out of service.")
    hours_problem = operating_hours_problem(venue, start, end)
    if hours_problem:
        reasons.append(hours_problem)
    if current["blocks"]:
        reasons.append("Recorded venue blocks overlap this period.")
    if current["conflicts"]:
        reasons.append("Venue reservations overlap this period.")
    if venue.in_service and venue.opens_at and venue.closes_at and venue.operating_days:
        day = timezone.localtime(start).date()
        last_day = timezone.localtime(end).date()
        while day <= last_day:
            if day.weekday() in venue.operating_days:
                opening = timezone.make_aware(datetime.combine(day, venue.opens_at))
                closing = timezone.make_aware(datetime.combine(day, venue.closes_at))
                cursor, limit = max(start, opening), min(end, closing)
                for left, right in occupied:
                    if right <= cursor or left >= limit:
                        continue
                    if left > cursor:
                        free.append({"starts_at": cursor, "ends_at": left})
                    cursor = max(cursor, right)
                if cursor < limit:
                    free.append({"starts_at": cursor, "ends_at": limit})
            day += timedelta(days=1)
    full = len(free) == 1 and free[0] == {"starts_at": start, "ends_at": end}
    return {
        "venue_id": venue.pk,
        "name": venue.name,
        "status": "available" if full else "partial" if free else "unavailable",
        "available": full,
        "free_segments": free,
        "reasons": reasons,
    }
