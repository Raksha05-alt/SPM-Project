from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    ASSIGNMENT = "ASSIGNMENT", "Coordinator assigned"
    APPROVED = "APPROVED", "Request approved"
    CLARIFICATION = "CLARIFICATION", "Clarification requested"
    RESUBMITTED = "RESUBMITTED", "Request resubmitted"
    REJECTED = "REJECTED", "Request rejected"


# Assignment notices are unique per occurrence, not per lifetime of an event.
ONE_OFF_KINDS = (NotificationKind.APPROVED, NotificationKind.REJECTED)


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
    assignment = models.ForeignKey(
        "events.CoordinatorAssignment",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
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
            ),
            models.UniqueConstraint(
                fields=["recipient", "assignment"], name="unique_assignment_notice_recipient"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} notification for user {self.recipient_id}, event {self.event_id}"
