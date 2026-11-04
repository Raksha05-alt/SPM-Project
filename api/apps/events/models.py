from django.conf import settings
from django.db import models
from django.utils import timezone

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
    # SCRUM-58 AC4 - who confirmed the event, and when.
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_event_requests",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
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


class ChangeSource(models.TextChoices):
    """SCRUM-60 - the operation that made a recorded change."""

    EVENT_EDIT = "EVENT_EDIT", "Event details edited"
    # Recovered from SCRUM-61 audit entries, which named the fields but not their values.
    LEGACY_AUDIT = "LEGACY_AUDIT", "Earlier edit (values not recorded)"


class AppendOnlyError(Exception):
    """Recorded change history is never edited or deleted."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("Change history entries cannot be edited.")

    def delete(self):
        raise AppendOnlyError("Change history entries cannot be deleted.")


class EventFieldChange(models.Model):
    """SCRUM-60 - one field's before and after value, who changed it and when.

    Append-only: saving an existing entry, or deleting or bulk-updating
    entries, raises AppendOnlyError, and the API offers reads only. Values are
    stored as JSON (datetimes as ISO 8601). ``values_recorded`` is False for
    entries recovered from earlier audit records, whose values were never kept:
    they are shown as "not recorded", never invented.
    """

    event = models.ForeignKey(EventRequest, on_delete=models.CASCADE, related_name="field_changes")
    field = models.CharField(max_length=60)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    values_recorded = models.BooleanField(default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(
        max_length=20, choices=ChangeSource.choices, default=ChangeSource.EVENT_EDIT
    )
    changed_at = models.DateTimeField()

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["-changed_at", "-pk"]
        indexes = [models.Index(fields=["event", "-changed_at"])]

    def __str__(self) -> str:
        return f"{self.field} changed on event {self.event_id} at {self.changed_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError("Change history entries cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Change history entries cannot be deleted.")


class ChangeRequestStatus(models.TextChoices):
    """SCRUM-20 - where a change request stands. Decisions are made under SCRUM-78."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class EventChangeRequest(TimeStampedModel):
    """SCRUM-20 - an organiser's request to change a submitted or confirmed event.

    The shared change contract (Sprint 4 INTAKE). It never edits the event:
    ``proposed_values`` holds typed new values for named event fields only, and
    ``target_bookings`` / ``target_equipment_requests`` hold the IDs of this
    event's own arrangements the change concerns. ``source_values`` and
    ``source_digest`` record the event as it was when the request was made, so
    a later assessment (SCRUM-59/78) or apply (SCRUM-80) can tell when it is
    stale. ``revision`` counts amendments of the request itself.
    """

    event = models.ForeignKey(
        EventRequest, on_delete=models.PROTECT, related_name="change_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    # AC1 - what the organiser wants changed, and why.
    description = models.TextField()
    reason = models.TextField()
    proposed_values = models.JSONField(default=dict, blank=True)
    target_bookings = models.JSONField(default=list, blank=True)
    target_equipment_requests = models.JSONField(default=list, blank=True)
    source_values = models.JSONField(default=dict)
    source_digest = models.CharField(max_length=64)
    source_status = models.CharField(max_length=20, choices=EventStatus.choices)
    revision = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=20, choices=ChangeRequestStatus.choices, default=ChangeRequestStatus.PENDING
    )
    status_changed_at = models.DateTimeField(default=timezone.now)
    # AC5 - the decision, recorded by the coordinator under SCRUM-78.
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]
        indexes = [models.Index(fields=["event", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ChangeRequestStatus.values),
                name="change_request_valid_status",
            ),
            # AC3 - a request always says what is to change, and why.
            models.CheckConstraint(
                condition=~models.Q(description__regex=r"^\s*$"),
                name="change_request_has_description",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason__regex=r"^\s*$"),
                name="change_request_has_reason",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=ChangeRequestStatus.PENDING, decided_at__isnull=True)
                    | (
                        ~models.Q(status=ChangeRequestStatus.PENDING)
                        & models.Q(decided_at__isnull=False)
                    )
                ),
                name="change_request_decision_time",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=ChangeRequestStatus.REJECTED)
                | ~models.Q(decision_reason=""),
                name="change_request_rejection_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"Change request {self.pk} for event {self.event_id} [{self.status}]"


class VenuePeriodReview(models.Model):
    """SCRUM-70: proposed period, separate from the still-occupied booking.

    A clear assessment is not a staff decision. APPLY supplies that decision
    and replaces arrangements only after all required resource checks pass.
    """

    booking = models.ForeignKey(
        "venues.VenueBooking", on_delete=models.PROTECT, related_name="period_reviews"
    )
    change_request = models.ForeignKey(EventChangeRequest, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    conflicts = models.JSONField(default=list)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    raised_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "change_request", "revision"],
                name="unique_booking_change_period_review",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="venue_review_positive_period",
            ),
        ]

    def __str__(self):
        return f"Period review for booking {self.booking_id}, change {self.change_request_id}"


class VenueReview(models.Model):
    """SCRUM-66 - an approved venue booking flagged for review after the event changed.

    Raised when a change to the event's attendance, layout or accessibility
    needs means the booked venue no longer suits it (AC1/AC2). ``reasons`` are
    the unmet requirements, as SCRUM-71 words them, and stay on record (AC3).
    At most one review per booking is open. It is resolved - never deleted -
    when a later change makes the venue suitable again, when a newer review
    replaces it, or when the booking stops being approved.
    """

    event = models.ForeignKey(EventRequest, on_delete=models.CASCADE, related_name="venue_reviews")
    booking = models.ForeignKey(
        "venues.VenueBooking", on_delete=models.PROTECT, related_name="suitability_reviews"
    )
    reasons = models.JSONField(default=list)
    changed_fields = models.JSONField(default=list)
    source = models.CharField(
        max_length=20, choices=ChangeSource.choices, default=ChangeSource.EVENT_EDIT
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    raised_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ["-raised_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["booking"],
                condition=models.Q(resolved_at__isnull=True),
                name="one_open_venue_review_per_booking",
            ),
        ]

    def __str__(self) -> str:
        state = "open" if self.resolved_at is None else "resolved"
        return f"Venue review of booking {self.booking_id} ({state})"
