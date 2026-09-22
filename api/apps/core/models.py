from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Auditability requirement: every row knows when it was created and changed."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """US-01.2 AC4 - a refused request is recorded with the user, action and time."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    allowed = models.BooleanField(default=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["actor", "-created_at"])]

    def __str__(self) -> str:
        outcome = "allowed" if self.allowed else "refused"
        return f"{self.action} ({outcome}) by {self.actor_id} at {self.created_at:%Y-%m-%d %H:%M}"
