"""EP-18 - Attendees registering for confirmed events."""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class RegistrationStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Registered"
    WAITLISTED = "WAITLISTED", "On waiting list"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


ACTIVE_STATUSES = (RegistrationStatus.REGISTERED, RegistrationStatus.WAITLISTED)


class Registration(TimeStampedModel):
    """SCRUM-21 / SCRUM-14 / SCRUM-19 - one Attendee's place (or wait) for an event.

    A withdrawn registration stays on record (SCRUM-14 AC5); registering again
    creates a new row, so at most one row per attendee and event is active.
    """

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="registrations"
    )
    attendee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="registrations"
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    accessibility_needs = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.REGISTERED
    )
    registered_at = models.DateTimeField(null=True, blank=True)
    waitlisted_at = models.DateTimeField(null=True, blank=True)
    # SCRUM-19 AC5 - when a waiting Attendee was told a place had become available.
    place_offered_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "attendee"],
                condition=models.Q(status__in=["REGISTERED", "WAITLISTED"]),
                name="one_active_registration_per_attendee",
            )
        ]

    def __str__(self) -> str:
        return f"{self.full_name} for event {self.event_id} ({self.get_status_display()})"
