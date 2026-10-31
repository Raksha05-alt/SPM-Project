"""SCRUM-90 (Week 7 change 6) - the Operational Safety Check.

Once an event's venue and technical arrangements are approved, its coordinator
sends it to the Safety Officers. One of them approves it, rejects it or
requests changes. The event cannot be confirmed until its current check is
approved.

A check is evidence, so it is never edited after its decision and never
deleted. When the arrangements it covered change, it is marked SUPERSEDED and a
new check is needed.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class SafetyStatus(models.TextChoices):
    PENDING = "PENDING", "Awaiting Safety Officer"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
    SUPERSEDED = "SUPERSEDED", "Superseded by a later change"


# What a Safety Officer may decide (AC3).
DECISIONS = (SafetyStatus.APPROVED, SafetyStatus.REJECTED, SafetyStatus.CHANGES_REQUESTED)
# A check that still stands: waiting for a decision, or approved and unchanged since.
CURRENT_STATUSES = (SafetyStatus.PENDING, SafetyStatus.APPROVED)


class SafetyCheck(models.Model):
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.PROTECT, related_name="safety_checks"
    )
    status = models.CharField(
        max_length=20, choices=SafetyStatus.choices, default=SafetyStatus.PENDING
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    request_note = models.TextField(blank=True)
    # AC2 - the facts the Safety Officer reviewed, kept as evidence of what was
    # approved even after the arrangements later change.
    facts = models.JSONField(default=dict, blank=True)
    # The reviewed arrangement version: a fingerprint of the venue bookings,
    # equipment, date, time and attendance when the check was requested. If the
    # event's current version differs, this check cannot approve it (AC6).
    arrangement_version = models.CharField(max_length=64)

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]
        constraints = [
            # At most one pending or approved check per event at any time.
            models.UniqueConstraint(
                fields=["event"],
                condition=Q(status__in=["PENDING", "APPROVED"]),
                name="one_current_safety_check_per_event",
            ),
            # AC3 - a decision always records who made it and when.
            models.CheckConstraint(
                condition=(
                    Q(status__in=["PENDING", "SUPERSEDED"])
                    | Q(decided_by__isnull=False, decided_at__isnull=False)
                ),
                name="safety_decision_has_actor_and_time",
            ),
            # AC3 - rejecting or requesting changes always says why.
            models.CheckConstraint(
                condition=~Q(status__in=["REJECTED", "CHANGES_REQUESTED"]) | ~Q(comment=""),
                name="safety_negative_decision_has_comment",
            ),
        ]

    def __str__(self) -> str:
        return f"Safety check for event {self.event_id} ({self.get_status_display()})"
