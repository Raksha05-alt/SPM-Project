from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Persistent, recipient-only coordinator assignment messages."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event"], name="unique_assignment_notification"
            )
        ]

    def __str__(self):
        return f"Assignment notification for user {self.recipient_id}, event {self.event_id}"
