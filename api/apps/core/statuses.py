"""Event status machine.

Lives in core rather than events because EP-06 and EP-07 will apply to venue
bookings and equipment reservations in later sprints, not only to events.
The history rows themselves belong to the component that owns the object.
"""

from django.db import models


class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Awaiting Clarification"
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
    EventStatus.UNDER_REVIEW: "A coordinator has asked the client for more information before continuing.",
    EventStatus.APPROVED: "ConnectSphere has agreed to plan this event.",
    EventStatus.PLANNING: "Venue, equipment and other arrangements are being made.",
    EventStatus.CONFIRMED: "All essential arrangements are in place. The event is going ahead.",
    EventStatus.COMPLETED: "The event has taken place and has been closed.",
    EventStatus.CANCELLED: "The event will not go ahead. Any arrangements have been released.",
    EventStatus.REJECTED: "ConnectSphere is not able to support this request.",
}

# SCRUM-54 - what the assigned coordinator has to do next, and whether that
# step is theirs to take (True) or they are waiting on someone else (False).
COORDINATOR_NEXT_ACTIONS: dict[str, tuple[str, bool]] = {
    EventStatus.DRAFT: ("No action - the client is still writing the request.", False),
    EventStatus.SUBMITTED: ("Review the request and approve, reject or ask for detail.", True),
    EventStatus.UNDER_REVIEW: ("Waiting for the client to answer your questions.", False),
    EventStatus.APPROVED: ("Start planning the venue and equipment.", True),
    EventStatus.PLANNING: ("Finish the arrangements and confirm the event.", True),
    EventStatus.CONFIRMED: ("Run the event, then mark it completed.", False),
    EventStatus.COMPLETED: ("No action - the event is closed.", False),
    EventStatus.CANCELLED: ("No action - the event was cancelled.", False),
    EventStatus.REJECTED: ("No action - the request was rejected.", False),
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

ATTENDEE_VISIBLE_STATUSES = frozenset(
    {
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
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

# Approve a submitted request - a coordinator may approve only from these.
REVIEWABLE_STATUSES = frozenset({EventStatus.SUBMITTED, EventStatus.UNDER_REVIEW})

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
