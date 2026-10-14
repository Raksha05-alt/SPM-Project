"""Week 7 change 6 - the Operational Safety Check.

Once the venue and technical arrangements are in place, the coordinator sends the
event to the Safety Officers. One of them approves it, rejects the safety
arrangement or requests changes, always with the option of a comment. The event
cannot be confirmed until the current check is approved.

A check is evidence, so it is never deleted. When the arrangements it approved
change, it is marked SUPERSEDED and a new check is needed.
"""

from django.conf import settings
from django.db import models


class SafetyStatus(models.TextChoices):
    PENDING = "PENDING", "Awaiting Safety Officer"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
    SUPERSEDED = "SUPERSEDED", "Superseded by a later change"


DECISIONS = (SafetyStatus.APPROVED, SafetyStatus.REJECTED, SafetyStatus.CHANGES_REQUESTED)
# A check that still stands: waiting for a decision, or approved and unchanged since.
CURRENT_STATUSES = (SafetyStatus.PENDING, SafetyStatus.APPROVED)


class SafetyCheck(models.Model):
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="safety_checks"
    )
    status = models.CharField(
        max_length=20, choices=SafetyStatus.choices, default=SafetyStatus.PENDING
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    request_note = models.TextField(blank=True)
    # The facts the Safety Officer was shown when the check was requested.
    facts = models.JSONField(default=dict, blank=True)

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
            # At most one check per event is pending or approved at any time.
            models.UniqueConstraint(
                fields=["event"],
                condition=models.Q(status__in=["PENDING", "APPROVED"]),
                name="one_current_safety_check_per_event",
            )
        ]

    def __str__(self) -> str:
        return f"Safety check for event {self.event_id} ({self.get_status_display()})"
