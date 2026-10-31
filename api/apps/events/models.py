from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.statuses import EventStatus


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

    # A LayoutType code from the SCRUM-91 catalogue; blank means no preference.
    required_layout = models.CharField(max_length=20, blank=True)
    accessibility_needs = models.TextField(blank=True)
    equipment_notes = models.TextField(blank=True)
    registration_required = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    assignment_requires_attention = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

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
    supervising_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supervised_event_requests",
    )
    assignment_revision = models.PositiveIntegerField(default=0)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_event_requests",
    )
    # SCRUM-61 AC4 - who last edited the request; ``updated_at`` records when.
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


class CoordinatorAssignment(models.Model):
    """SCRUM-53/89: immutable assignment occurrences, including A → B → A."""

    event = models.ForeignKey(
        EventRequest, on_delete=models.CASCADE, related_name="assignment_history"
    )
    previous_coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="previous_assignments",
    )
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignment_occurrences"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_made"
    )
    previous_supervising_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="previous_supervisions",
    )
    revision = models.PositiveIntegerField()
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "revision"], name="unique_event_assignment_revision"
            )
        ]

    def __str__(self):
        return f"Event {self.event_id}: assignment {self.revision}"


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


class ClarificationComment(models.Model):
    """SCRUM-92 - a note recording a clarification conversation held offline.

    Notes are append-only: there is no edit or delete, so what was agreed stays
    on the request with its author and time.
    """

    clarification = models.ForeignKey(
        ClarificationRequest, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"Note on clarification {self.clarification_id} by {self.author_id}"
