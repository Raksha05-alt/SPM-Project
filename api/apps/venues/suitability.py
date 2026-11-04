"""SCRUM-71 - the shared venue suitability assessment (Sprint 3 gate G07).

One assessment answers "does this venue meet these requirements?" and states
every requirement it does not meet. It is used by:

* ``GET /api/events/<id>/venue-suitability/``, for the assigned coordinator;
* the venue booking request action (SCRUM-11, gate G09), which must refuse an
  unsuitable venue with these reasons (AC4) by calling ``ensure_suitable``;
* Venue Staff booking decisions (SCRUM-72, gate G10), which recheck it under
  the booking locks;
* later event-change handlers (SCRUM-66, Sprint 4).

Suitability is separate from availability. A suitable room can still be booked,
blocked or out of service, and a free room can still be unsuitable; occupancy
and blocks belong to ``apps.venues.availability`` and SCRUM-69. SCRUM-85
adds advisory setup/turnaround operating-hours warnings, separate from suitability.

Rules:

* Capacity: attendance equal to the venue's capacity fits (AC1).
* Layout: a layout code from the SCRUM-91 catalogue must be recorded on the
  venue; reasons use the catalogue's current name (AC2).
* Wheelchair access: met only when the venue records it. Not recorded is not
  assumed to be met (AC2).
* Required facilities: each must be recorded on the venue, ignoring case and
  surrounding spaces. Free-text accessibility notes are kept for staff to read
  and are not interpreted here.
* Operating hours: ``apps.venues.availability.operating_hours_problem``, the
  shared Singapore-time rule; missing hours cannot establish a match (AC3).
"""

from dataclasses import dataclass, field

from apps.venues.availability import buffer_hours_warning, operating_hours_problem
from apps.venues.layouts import label_map

WHEELCHAIR_ACCESS = "Wheelchair access"


class Requirement:
    CAPACITY = "CAPACITY"
    LAYOUT = "LAYOUT"
    ACCESSIBILITY = "ACCESSIBILITY"
    FACILITY = "FACILITY"
    OPERATING_HOURS = "OPERATING_HOURS"


@dataclass(frozen=True)
class Reason:
    requirement: str
    message: str

    def as_dict(self) -> dict:
        return {"requirement": self.requirement, "message": self.message}


def clean_facilities(names) -> list[str]:
    """Strip blanks and repeats (ignoring case), keeping the order the caller gave."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names or []:
        name = str(name).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            cleaned.append(name)
    return cleaned


@dataclass(frozen=True)
class Requirements:
    """What a venue must meet, wherever the requirements come from.

    Build it from an event (``for_event``) or from a booking request's stored
    requirements (``for_booking``), so the request guard never depends on a
    coordinator first visiting the suitability page.
    """

    attendance: int | None = None
    layout: str = ""
    required_facilities: tuple[str, ...] = ()
    wheelchair_access_required: bool = False
    starts_at: object = None
    ends_at: object = None

    def __post_init__(self):
        # "Wheelchair access" typed as a facility is the structured requirement.
        names = clean_facilities(self.required_facilities)
        wheelchair = [n for n in names if n.casefold() == WHEELCHAIR_ACCESS.casefold()]
        others = tuple(n for n in names if n not in wheelchair)
        object.__setattr__(self, "required_facilities", others)
        object.__setattr__(
            self, "wheelchair_access_required", bool(self.wheelchair_access_required or wheelchair)
        )
        object.__setattr__(self, "layout", self.layout or "")

    @classmethod
    def for_event(cls, event, *, required_facilities=(), wheelchair_access_required=False):
        """The event's attendance, layout and preferred period, plus the facilities and
        wheelchair access the coordinator says are required."""
        return cls(
            attendance=event.expected_attendance,
            layout=event.required_layout,
            required_facilities=tuple(required_facilities),
            wheelchair_access_required=wheelchair_access_required,
            starts_at=event.preferred_start,
            ends_at=event.preferred_end,
        )

    @classmethod
    def for_booking(cls, booking):
        """A venue booking request's stored requirements (SCRUM-11 booking contract).

        Accepts a ``VenueBooking`` or any object with the same fields, such as the
        cleaned values a request action is about to save.
        """
        return cls(
            attendance=(
                booking.event.expected_attendance
                if getattr(booking, "session", None) is not None and booking.session.kind == "MAIN"
                else booking.attendance
            ),
            layout=booking.layout,
            required_facilities=tuple(booking.required_facilities or ()),
            wheelchair_access_required=booking.wheelchair_access_required,
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
        )

    def as_dict(self, labels: dict[str, str]) -> dict:
        return {
            "attendance": self.attendance,
            "layout": self.layout,
            "layout_name": labels.get(self.layout, self.layout) if self.layout else "",
            "required_facilities": list(self.required_facilities),
            "wheelchair_access_required": self.wheelchair_access_required,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
        }


@dataclass
class Suitability:
    venue_id: int
    venue_name: str
    reasons: list[Reason] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def suitable(self) -> bool:
        # AC5 - a venue meeting every requirement has no warnings.
        return not self.reasons

    def as_dict(self) -> dict:
        return {
            **({"warnings": self.warnings} if self.warnings else {}),
            "venue": self.venue_id,
            "venue_name": self.venue_name,
            "suitable": self.suitable,
            "reasons": [r.as_dict() for r in self.reasons],
        }


class VenueUnsuitable(Exception):
    """AC4 - raised by ``ensure_suitable``; ``reasons`` lists every unmet requirement."""

    def __init__(self, result: Suitability):
        self.result = result
        self.reasons = result.reasons
        super().__init__(
            f"{result.venue_name} does not meet this event's requirements: "
            + " ".join(r.message for r in result.reasons)
        )


def _capacity(venue, req) -> Reason | None:
    if req.attendance is None or req.attendance <= venue.capacity:
        return None
    return Reason(
        Requirement.CAPACITY,
        f"Expected attendance of {req.attendance} exceeds the venue's maximum capacity of "
        f"{venue.capacity}.",
    )


def _layout(venue, req, labels) -> Reason | None:
    if not req.layout or req.layout in venue.layouts:
        return None
    name = labels.get(req.layout, req.layout)
    return Reason(Requirement.LAYOUT, f"The venue does not support the required {name} layout.")


def _wheelchair(venue, req) -> Reason | None:
    if not req.wheelchair_access_required:
        return None
    listed = WHEELCHAIR_ACCESS.casefold() in {f.strip().casefold() for f in venue.facilities}
    if venue.wheelchair_access is True or (venue.wheelchair_access is None and listed):
        return None
    if venue.wheelchair_access is False:
        message = "The venue does not have the required wheelchair access."
    else:
        message = "The venue's wheelchair access is not recorded, so it cannot be confirmed."
    return Reason(Requirement.ACCESSIBILITY, message)


def _facilities(venue, req) -> list[Reason]:
    offered = {f.strip().casefold() for f in venue.facilities}
    return [
        Reason(Requirement.FACILITY, f"The venue does not offer the required facility: {name}.")
        for name in req.required_facilities
        if name.casefold() not in offered
    ]


def _operating_hours(venue, req) -> Reason | None:
    # A period is needed to check hours; event requests always have one once
    # submitted (US-02.2), and booking requests always do (SCRUM-11).
    if req.starts_at is None or req.ends_at is None:
        return None
    problem = operating_hours_problem(venue, req.starts_at, req.ends_at)
    return Reason(Requirement.OPERATING_HOURS, problem) if problem else None


def assess(venue, requirements: Requirements, *, labels: dict[str, str] | None = None):
    """Every requirement ``venue`` does not meet, in a fixed order (AC1-AC3, AC5).

    ``labels`` is the layout catalogue's code-to-name map; pass it when checking
    several venues so the catalogue is read once.
    """
    labels = label_map() if labels is None else labels
    result = Suitability(venue_id=venue.pk, venue_name=venue.name)
    for reason in (
        _capacity(venue, requirements),
        _layout(venue, requirements, labels),
        _wheelchair(venue, requirements),
        *_facilities(venue, requirements),
        _operating_hours(venue, requirements),
    ):
        if reason is not None:
            result.reasons.append(reason)
    if requirements.starts_at and requirements.ends_at:
        warning = buffer_hours_warning(venue, requirements.starts_at, requirements.ends_at)
        if warning:
            result.warnings.append(warning)
    return result


def ensure_suitable(venue, requirements: Requirements) -> Suitability:
    """AC4 guard for the request (G09) and decision (G10) actions.

    Returns the passing assessment, or raises VenueUnsuitable with every reason.
    Call it inside the action's transaction, after locking the venue row, so the
    venue record cannot change between this check and the save.
    """
    result = assess(venue, requirements)
    if not result.suitable:
        raise VenueUnsuitable(result)
    return result


def check_suitability(
    event, venue, required_facilities=(), wheelchair_access_required=False, labels=None
):
    """Convenience: assess ``venue`` against ``event``'s requirements."""
    return assess(
        venue,
        Requirements.for_event(
            event,
            required_facilities=required_facilities,
            wheelchair_access_required=wheelchair_access_required,
        ),
        labels=labels,
    )
