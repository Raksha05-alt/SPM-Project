"""SCRUM-17: fresh availability, using Singapore operating hours.

Intervals are half-open: a block ending at 10:00 does not obstruct a 10:00 start.
Missing operating hours are unavailable rather than assumed to be open.
Approved bookings occupy the actual event period; holds belong to Sprint 4.
"""

from django.utils import timezone

from apps.venues.occupancy import conflict_references

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


def availability(venue, start, end):
    # Discovery checks several venues at once. Reuse its request-scoped prefetch
    # without changing the same half-open overlap rule used by direct checks.
    if "blocks" in getattr(venue, "_prefetched_objects_cache", {}):
        blocks = [b for b in venue.blocks.all() if b.starts_at < end and b.ends_at > start]
    else:
        blocks = list(venue.blocks.filter(starts_at__lt=end, ends_at__gt=start))
    if hasattr(venue, "occupancy_bookings"):
        conflicts = [
            {"id": b.pk, "event_id": b.event_id, "starts_at": b.starts_at, "ends_at": b.ends_at}
            for b in venue.occupancy_bookings
            if b.starts_at < end and b.ends_at > start
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
