"""SCRUM-17: fresh availability, using Singapore operating hours.

Intervals are half-open: a block ending at 10:00 does not obstruct a 10:00 start.
Missing operating hours are unavailable rather than assumed to be open.
Booking/hold integration is deliberately left to the agreed booking contract.
"""

from django.utils import timezone


def within_operating_hours(venue, start, end):
    if not venue.opens_at or not venue.closes_at or not venue.operating_days:
        return False
    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    # The existing venue contract has same-day opening/closing hours. A continuous
    # interval spanning nights necessarily includes closed time.
    return (
        local_start.date() == local_end.date()
        and local_start.weekday() in venue.operating_days
        and local_start.time() >= venue.opens_at
        and local_end.time() <= venue.closes_at
    )


def availability(venue, start, end):
    blocks = list(venue.blocks.filter(starts_at__lt=end, ends_at__gt=start))
    if blocks:
        status = "blocked"
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
        "blocks": [
            {"id": b.pk, "reason": b.reason, "starts_at": b.starts_at, "ends_at": b.ends_at}
            for b in blocks
        ],
    }
