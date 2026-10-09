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
    # SCRUM-81 / SCRUM-19 - how many places, when registration is open, and
    # whether a full event keeps a waiting list. Capacity defaults to the
    # expected attendance when left empty.
    registration_capacity = models.PositiveIntegerField(null=True, blank=True)
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    waitlist_enabled = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    assignment_requires_attention = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    # SCRUM-58 AC4 - who confirmed the event, and when.
    confirmed_at = models.DateTimeField(null=True, blank=True)

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
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_event_requests",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_event_requests",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
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


class ClarificationRequest(models.Model):
    """A coordinator's request for missing or unclear information.

    Rows are kept after the client answers, so the full clarification history
    stays with the event.
    """

    event = models.ForeignKey(EventRequest, on_delete=models.CASCADE, related_name="clarifications")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    message = models.TextField()
    fields = models.JSONField(default=list, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]

    def __str__(self) -> str:
        state = "answered" if self.resolved_at else "open"
        return f"Clarification on {self.event_id} ({state})"


class CoordinatorAssignment(models.Model):
    """SCRUM-51 / SCRUM-53 - who has coordinated an event, kept after each change."""

    event = models.ForeignKey(
        EventRequest, on_delete=models.CASCADE, related_name="assignment_history"
    )
    previous_coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Null when the system made the automatic assignment on submission.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.event_id}: {self.previous_coordinator_id} -> {self.coordinator_id}"


class ImmutableRecord(Exception):
    """Raised when code tries to edit or delete a history row."""


class EventChangeLog(models.Model):
    """SCRUM-60 - one row per changed field. Rows are evidence, so they never change."""

    event = models.ForeignKey(EventRequest, on_delete=models.CASCADE, related_name="change_log")
    field = models.CharField(max_length=60)
    previous_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    significant = models.BooleanField(default=False)

    class Meta:
        ordering = ["-changed_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.event_id}.{self.field}: {self.previous_value!r} -> {self.new_value!r}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ImmutableRecord("Change history entries cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecord("Change history entries cannot be deleted.")


class ChangeRequestStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class ChangeRequest(models.Model):
    """SCRUM-20 / SCRUM-78 - a client's request to change a submitted event.

    The ``proposed_*`` fields hold the new values the client asks for; any
    left empty stay as they are. The description says what and why in words.
    """

    event = models.ForeignKey(
        EventRequest, on_delete=models.CASCADE, related_name="change_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    description = models.TextField()
    reason = models.TextField(blank=True)
    proposed_start = models.DateTimeField(null=True, blank=True)
    proposed_end = models.DateTimeField(null=True, blank=True)
    proposed_attendance = models.PositiveIntegerField(null=True, blank=True)
    proposed_layout = models.CharField(max_length=20, choices=RoomLayout.choices, blank=True)
    proposed_accessibility_needs = models.TextField(blank=True)
    proposed_equipment_notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=ChangeRequestStatus.choices, default=ChangeRequestStatus.PENDING
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Change to event {self.event_id} ({self.get_status_display()})"

    def proposed_values(self) -> dict:
        """The event fields this request would change, with their new values."""
        mapping = {
            "preferred_start": self.proposed_start,
            "preferred_end": self.proposed_end,
            "expected_attendance": self.proposed_attendance,
            "required_layout": self.proposed_layout,
            "accessibility_needs": self.proposed_accessibility_needs,
            "equipment_notes": self.proposed_equipment_notes,
        }
        return {field: value for field, value in mapping.items() if value not in (None, "")}
