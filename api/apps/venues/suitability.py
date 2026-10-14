"""SCRUM-71 - does a venue appear suitable for an event, and if not, why not?"""

from django.utils import timezone

from apps.venues.matching import inside_operating_hours
from apps.venues.models import layout_label
from apps.venues.serializers import describe_hours


def requirements_of(event, **overrides) -> dict:
    """The venue-relevant requirements of an event, optionally replaced (for a booking)."""
    needs = {
        "attendance": event.expected_attendance,
        "layout": event.required_layout,
        "accessibility_needs": event.accessibility_needs,
        "start": event.preferred_start,
        "end": event.preferred_end,
        "facilities": [],
    }
    needs.update({key: value for key, value in overrides.items() if value is not None})
    return needs


def assess(venue, needs: dict) -> list[dict]:
    """One check per requirement that was stated, each with a plain-language reason."""
    checks = [
        {
            "criterion": "Operational status",
            "matches": venue.is_active,
            "reason": "" if venue.is_active else f"{venue.name} is out of service.",
        }
    ]
    attendance = needs.get("attendance")
    if attendance:
        ok = venue.capacity >= attendance
        checks.append(
            {
                "criterion": "Capacity",
                "matches": ok,
                "reason": ""
                if ok
                else (
                    f"Expected attendance of {attendance} exceeds the venue's "
                    f"capacity of {venue.capacity}."
                ),
            }
        )
    layout = needs.get("layout")
    if layout:
        ok = layout in venue.layouts
        checks.append(
            {
                "criterion": "Room layout",
                "matches": ok,
                "reason": ""
                if ok
                else f"The venue does not support the {layout_label(layout)} layout.",
            }
        )
    if (needs.get("accessibility_needs") or "").strip():
        ok = venue.wheelchair_access is True
        checks.append(
            {
                "criterion": "Accessibility",
                "matches": ok,
                "reason": ""
                if ok
                else "The event has accessibility needs and the venue has no recorded step-free access.",
            }
        )
    facilities = needs.get("facilities") or []
    if facilities:
        available = {value.casefold() for value in venue.facilities}
        missing = [value for value in facilities if value.casefold() not in available]
        checks.append(
            {
                "criterion": "Facilities",
                "matches": not missing,
                "reason": "" if not missing else f"Missing facilities: {', '.join(missing)}.",
            }
        )
    start, end = needs.get("start"), needs.get("end")
    if start and end:
        ok = inside_operating_hours(venue, start, end)
        hours = describe_hours(venue) or "not recorded"
        checks.append(
            {
                "criterion": "Operating hours",
                "matches": ok,
                "reason": ""
                if ok
                else f"The event's timing falls outside the venue's operating hours ({hours}).",
            }
        )
    return checks


def unmet(checks) -> list[str]:
    return [check["reason"] for check in checks if not check["matches"]]


def buffer_warnings(booking) -> list[str]:
    """Week 7 clarification - Venue Staff decide whether setup and turnaround may fall
    outside opening hours, so the system warns rather than refuses."""
    venue = booking.venue
    if not (venue.setup_minutes or venue.turnaround_minutes):
        return []
    if venue.opens_at is None or venue.closes_at is None:
        return []
    start, end = booking.occupied_start, booking.occupied_end
    if inside_operating_hours(venue, start, end):
        return []
    return [
        f"With setup and turnaround the venue is needed from "
        f"{timezone.localtime(start):%H:%M} to {timezone.localtime(end):%H:%M}, outside its "
        f"operating hours ({describe_hours(venue)})."
    ]
