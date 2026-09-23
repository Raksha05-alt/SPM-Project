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

