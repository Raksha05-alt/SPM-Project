"""SCRUM-71 - flag venues that do not meet the event's requirements.

A suitability check compares one event request with one venue and states every
requirement the venue does not meet. It is separate from availability: a
suitable venue may still be booked or blocked for that period, and an empty
venue may still be unsuitable.

Provisional rules, pending a team decision (see docs/testing/SCRUM-71.md):

* Required accessibility facilities are supplied with the check, because
  ``EventRequest.accessibility_needs`` is free text. "Wheelchair access" is met
  by ``Venue.wheelchair_access``; any other facility must appear in
  ``Venue.facilities`` (case-insensitive).
* A venue whose operating hours are not recorded cannot be shown to cover the
  event, so it is flagged with that reason.
* An event may start exactly at opening and end exactly at closing. Times are
  compared in the project time zone (``settings.TIME_ZONE``).
"""

from dataclasses import asdict, dataclass, field
from datetime import timedelta

from django.utils import timezone

from apps.events.models import RoomLayout

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

WHEELCHAIR_ACCESS = "Wheelchair access"


class Requirement:
    CAPACITY = "CAPACITY"
    LAYOUT = "LAYOUT"
    ACCESSIBILITY = "ACCESSIBILITY"
    OPERATING_HOURS = "OPERATING_HOURS"


@dataclass(frozen=True)
class Reason:
    requirement: str
    message: str


@dataclass
class Suitability:
    venue_id: int
    venue_name: str
    reasons: list[Reason] = field(default_factory=list)

    @property
    def suitable(self) -> bool:
        return not self.reasons

    def as_dict(self) -> dict:
        return {
            "venue": self.venue_id,
            "venue_name": self.venue_name,
            "suitable": self.suitable,
            "reasons": [asdict(r) for r in self.reasons],
        }


def clean_facilities(names) -> list[str]:
    """Strip blanks and duplicates while keeping the order the caller gave."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names or []:
        name = str(name).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            cleaned.append(name)
    return cleaned


def _capacity(event, venue) -> Reason | None:
    # AC1 - exactly the venue's capacity still fits.
    attendance = event.expected_attendance
    if attendance is None or attendance <= venue.capacity:
        return None
    return Reason(
        Requirement.CAPACITY,
        f"Expected attendance of {attendance} exceeds the venue's maximum capacity of "
        f"{venue.capacity}.",
    )


def _layout(event, venue) -> Reason | None:
    # AC2 - the required room layout.
    required = event.required_layout
    if not required or required in venue.layouts:
        return None
    label = RoomLayout(required).label if required in RoomLayout.values else required
    return Reason(
        Requirement.LAYOUT,
        f"The venue does not support the required {label} layout.",
    )


def _accessibility(venue, required_facilities) -> list[Reason]:
    # AC2 - each required accessibility facility.
    offered = {f.casefold() for f in venue.facilities}
    reasons = []
    for facility in clean_facilities(required_facilities):
        if facility.casefold() == WHEELCHAIR_ACCESS.casefold():
            met = venue.wheelchair_access is True or facility.casefold() in offered
        else:
            met = facility.casefold() in offered
        if not met:
            reasons.append(
                Reason(
                    Requirement.ACCESSIBILITY,
                    f"The venue does not offer the required accessibility facility: {facility}.",
                )
            )
    return reasons


def _operating_hours(event, venue) -> Reason | None:
    # AC3 - the event's timing must fall inside the venue's operating hours.
    start, end = event.preferred_start, event.preferred_end
    if start is None or end is None:
        return None
    if venue.opens_at is None or venue.closes_at is None or not venue.operating_days:
        return Reason(
            Requirement.OPERATING_HOURS,
            "The venue's operating hours are not recorded, so the event timing cannot be "
            "confirmed.",
        )

    start = timezone.localtime(start)
    end = timezone.localtime(end)
    hours = f"{venue.opens_at:%H:%M}-{venue.closes_at:%H:%M}"

    day = start.date()
    while day <= end.date():
        if day.weekday() not in venue.operating_days:
            return Reason(
                Requirement.OPERATING_HOURS,
                f"The event falls on a {DAY_NAMES[day.weekday()]}, when the venue is closed.",
            )
        day += timedelta(days=1)

    if start.date() != end.date():
        return Reason(
            Requirement.OPERATING_HOURS,
            f"The event runs overnight, outside the venue's operating hours of {hours}.",
        )
    if start.time() < venue.opens_at or end.time() > venue.closes_at:
        return Reason(
            Requirement.OPERATING_HOURS,
            f"The event runs {start:%H:%M}-{end:%H:%M}, outside the venue's operating hours "
            f"of {hours}.",
        )
    return None


def check_suitability(event, venue, required_facilities=()) -> Suitability:
    """Return every requirement of ``event`` that ``venue`` does not meet (AC1-3, AC5)."""
    result = Suitability(venue_id=venue.pk, venue_name=venue.name)
    for reason in (
        _capacity(event, venue),
        _layout(event, venue),
        *_accessibility(venue, required_facilities),
        _operating_hours(event, venue),
    ):
        if reason is not None:
            result.reasons.append(reason)
    return result
