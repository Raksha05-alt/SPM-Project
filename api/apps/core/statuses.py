"""Event status machine.

Lives in core rather than events because EP-06 and EP-07 will apply to venue
bookings and equipment reservations in later sprints, not only to events.
The history rows themselves belong to the component that owns the object.
"""

from django.db import models


class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    APPROVED = "APPROVED", "Approved"
    PLANNING = "PLANNING", "Planning"
    CONFIRMED = "CONFIRMED", "Confirmed"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"


# US-06.1 AC2 - plain language explanation of every status.
STATUS_DESCRIPTIONS = {
    EventStatus.DRAFT: "Still being written by the client. ConnectSphere cannot see it yet.",
    EventStatus.SUBMITTED: "Sent to ConnectSphere and waiting to be picked up by a coordinator.",
    EventStatus.UNDER_REVIEW: "A coordinator is checking the request and may ask for more detail.",
    EventStatus.APPROVED: "ConnectSphere has agreed to plan this event.",
    EventStatus.PLANNING: "Venue, equipment and other arrangements are being made.",
    EventStatus.CONFIRMED: "All essential arrangements are in place. The event is going ahead.",
    EventStatus.COMPLETED: "The event has taken place and has been closed.",
    EventStatus.CANCELLED: "The event will not go ahead. Any arrangements have been released.",
    EventStatus.REJECTED: "ConnectSphere is not able to support this request.",
}

# US-06.1 AC4 - statuses that describe internal planning are not shown to
# external users such as Attendees.
INTERNAL_STATUSES = frozenset(
    {
        EventStatus.DRAFT,
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.REJECTED,
    }
)

# US-06.2 - a status may only change along one of these edges. Statuses that
# are not reachable in Sprint 1 are declared now so that the machine is
# complete and later sprints add behaviour, not structure.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    EventStatus.DRAFT: frozenset({EventStatus.SUBMITTED, EventStatus.CANCELLED}),
    EventStatus.SUBMITTED: frozenset(
        {
            EventStatus.UNDER_REVIEW,
            EventStatus.APPROVED,
            EventStatus.REJECTED,
            EventStatus.CANCELLED,
        }
    ),
    EventStatus.UNDER_REVIEW: frozenset(
        {EventStatus.APPROVED, EventStatus.REJECTED, EventStatus.SUBMITTED, EventStatus.CANCELLED}
    ),
    EventStatus.APPROVED: frozenset({EventStatus.PLANNING, EventStatus.CANCELLED}),
    EventStatus.PLANNING: frozenset({EventStatus.CONFIRMED, EventStatus.CANCELLED}),
    EventStatus.CONFIRMED: frozenset({EventStatus.COMPLETED, EventStatus.CANCELLED}),
    EventStatus.COMPLETED: frozenset(),
    EventStatus.CANCELLED: frozenset(),
    EventStatus.REJECTED: frozenset(),
}

TERMINAL_STATUSES = frozenset({EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED})


class InvalidTransition(Exception):
    """Raised when a status change is not permitted from the current status."""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot move from {EventStatus(current).label} to {EventStatus(target).label}."
        )


def validate_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(current, target)


def describe(status: str, *, for_internal_user: bool = True) -> dict:
    return {
        "value": status,
        "label": EventStatus(status).label,
        "description": STATUS_DESCRIPTIONS[status],
        "internal": status in INTERNAL_STATUSES,
        "visible": for_internal_user or status not in INTERNAL_STATUSES,
    }
