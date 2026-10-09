from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    ASSIGNMENT = "ASSIGNMENT", "Coordinator assigned"
    APPROVED = "APPROVED", "Request approved"
    CLARIFICATION = "CLARIFICATION", "Clarification requested"
    RESUBMITTED = "RESUBMITTED", "Request resubmitted"
    REJECTED = "REJECTED", "Request rejected"
    STATUS_CHANGED = "STATUS_CHANGED", "Event status changed"
    REASSIGNED = "REASSIGNED", "Coordinator reassigned"
    BOOKING_REQUESTED = "BOOKING_REQUESTED", "Venue booking requested"
    BOOKING_DECIDED = "BOOKING_DECIDED", "Venue booking decided"
    BOOKING_WITHDRAWN = "BOOKING_WITHDRAWN", "Venue booking withdrawn"
    EQUIPMENT_REQUESTED = "EQUIPMENT_REQUESTED", "Equipment requested"
    EQUIPMENT_CHANGED = "EQUIPMENT_CHANGED", "Equipment request changed"
    EQUIPMENT_RESERVED = "EQUIPMENT_RESERVED", "Equipment reserved"
    EQUIPMENT_RELEASED = "EQUIPMENT_RELEASED", "Equipment released"


# Sent at most once per recipient and event. Clarification rounds can repeat.
ONE_OFF_KINDS = (NotificationKind.ASSIGNMENT, NotificationKind.APPROVED, NotificationKind.REJECTED)


class Notification(models.Model):
    """Persistent, recipient-only messages about an event request."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(
        max_length=20, choices=NotificationKind.choices, default=NotificationKind.ASSIGNMENT
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event", "kind"],
                condition=models.Q(kind__in=ONE_OFF_KINDS),
                name="unique_notification_per_kind",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} notification for user {self.recipient_id}, event {self.event_id}"
