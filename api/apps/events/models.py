from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.statuses import EventStatus


class RoomLayout(models.TextChoices):
    CLASSROOM = "CLASSROOM", "Classroom"
    THEATRE = "THEATRE", "Theatre"
    BOARDROOM = "BOARDROOM", "Boardroom"
    BANQUET = "BANQUET", "Banquet"
    EXHIBITION = "EXHIBITION", "Exhibition"


class EventRequest(TimeStampedModel):
    """An event request raised by a client.

    Fields are nullable on purpose. US-03.1 AC2 requires a draft to save with
    empty fields; mandatory-field rules are applied at submission instead, by
    ``missing_mandatory_fields``.
    """

    MANDATORY_FOR_SUBMISSION = (
        "name",
        "purpose",
        "preferred_start",
        "preferred_end",
        "expected_attendance",
    )

    name = models.CharField(max_length=200, blank=True)
    purpose = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)

    preferred_start = models.DateTimeField(null=True, blank=True)
    preferred_end = models.DateTimeField(null=True, blank=True)
    expected_attendance = models.PositiveIntegerField(null=True, blank=True)

    required_layout = models.CharField(max_length=20, choices=RoomLayout.choices, blank=True)
    accessibility_needs = models.TextField(blank=True)
    equipment_notes = models.TextField(blank=True)
    registration_required = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    organisation = models.ForeignKey(
        "accounts.ClientOrganisation", on_delete=models.PROTECT, related_name="event_requests"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_event_requests"
    )
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coordinated_event_requests",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["organisation", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name or '(untitled draft)'} [{self.get_status_display()}]"

    @property
    def is_draft(self) -> bool:
        return self.status == EventStatus.DRAFT

    def missing_mandatory_fields(self) -> list[str]:
        """US-02.2 AC2 / US-03.1 AC2 - which fields block submission."""
        return [
            field
            for field in self.MANDATORY_FOR_SUBMISSION
            if getattr(self, field) in (None, "", 0)
            or (isinstance(getattr(self, field), str) and not getattr(self, field).strip())
        ]


class EventStatusHistory(models.Model):
    """US-06.2 / US-07.3 - every transition is recorded, and rows are never edited."""

    event = models.ForeignKey(EventRequest, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=EventStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=EventStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name_plural = "event status history"

    def __str__(self) -> str:
        return f"{self.event_id}: {self.from_status or 'new'} -> {self.to_status}"
