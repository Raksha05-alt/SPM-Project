"""Venue decision foundation for future search and shortlist integration.

These functions take validated venue facts and occupied periods, not database
rows or user permissions. Search periods require timezone-aware ISO timestamps.
They are not wired to an endpoint and do not yet expand setup/turnaround buffers.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

SINGAPORE = ZoneInfo("Asia/Singapore")


def _validate_period(start, end):
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Venue periods must include a timezone.")
    if end <= start:
        raise ValueError("Venue periods must end after they start.")


def periods_overlap(start, end, occupied_start, occupied_end):
    """Use half-open intervals: a booking ending at the next start does not clash."""
    _validate_period(start, end)
    _validate_period(occupied_start, occupied_end)
    return start < occupied_end and end > occupied_start


def inside_operating_hours(venue, start, end):
    _validate_period(start, end)
    start, end = start.astimezone(SINGAPORE), end.astimezone(SINGAPORE)
    if venue.opens_at is None or venue.closes_at is None:
        return False
    return (
        start.date() == end.date()
        and start.weekday() in venue.operating_days
        and venue.opens_at <= start.time()
        and end.time() <= venue.closes_at
    )


def compare_venue(venue, criteria, occupied_periods=()):
    """Return one explicit result for each supplied criterion, plus service status."""
    checks = [{"criterion": "Operational status", "matches": venue.is_active}]
    attendance = criteria.get("attendance")
    if attendance is not None:
        checks.append({"criterion": "Capacity", "matches": venue.capacity >= attendance})
    layout = criteria.get("layout")
    if layout:
        checks.append({"criterion": "Room layout", "matches": layout in venue.layouts})
    facilities = criteria.get("facilities", [])
    if facilities:
        available = {value.casefold() for value in venue.facilities}
        checks.append(
            {
                "criterion": "Facilities",
                "matches": all(value.casefold() in available for value in facilities),
            }
        )
    location = criteria.get("location")
    if location:
        checks.append(
            {"criterion": "Location", "matches": location.casefold() in venue.location.casefold()}
        )
    if criteria.get("wheelchair_access"):
        checks.append(
            {"criterion": "Wheelchair access", "matches": venue.wheelchair_access is True}
        )
    start_value, end_value = criteria.get("start"), criteria.get("end")
    if start_value or end_value:
        if not start_value or not end_value:
            raise ValueError("Venue searches require both start and end times.")
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
        checks.append(
            {"criterion": "Operating hours", "matches": inside_operating_hours(venue, start, end)}
        )
        checks.append(
            {
                "criterion": "Availability",
                "matches": not any(
                    periods_overlap(start, end, first, last) for first, last in occupied_periods
                ),
            }
        )
    return checks


def satisfies_all(checks):
    return all(check["matches"] for check in checks)
