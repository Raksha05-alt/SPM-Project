"""EP-18 - attendee registration (Sprint 4: SCRUM-21 register, SCRUM-81 capacity and period).

* ``RegistrationPolicy`` - the organiser's settings for one event: on/off,
  opening and closing times, manual closure and a registration cap that is
  separate from the venue's physical capacity (Week 4 G3 D24/D25/D48/D74).
* ``Registration`` - one attendee's place. At most one *active* registration per
  event and attendee; withdrawn rows are kept (SCRUM-14 adds withdrawal).
* ``RegistrationHistory`` and ``RegistrationPolicyChange`` - append-only records
  of every status change and every policy change, with who and when.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel


class RegistrationPolicy(TimeStampedModel):
    event = models.OneToOneField(
        "events.EventRequest", on_delete=models.CASCADE, related_name="registration_policy"
    )
    enabled = models.BooleanField(default=False)
    # SCRUM-81 - registration is open while opens_at <= now < closes_at.
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    manually_closed = models.BooleanField(default=False)
    # The organiser's registration cap, not the venue capacity.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name_plural = "registration policies"
        constraints = [
            models.CheckConstraint(
                condition=Q(opens_at__isnull=True)
                | Q(closes_at__isnull=True)
                | Q(closes_at__gt=F("opens_at")),
                name="registration_policy_closes_after_opening",
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gte=1),
                name="registration_policy_capacity_at_least_one",
            ),
        ]

    def __str__(self) -> str:
        return f"Registration policy for event {self.event_id}"


class RegistrationPolicyChange(models.Model):
    """Every change to a policy, before and after. Never edited."""

    policy = models.ForeignKey(RegistrationPolicy, on_delete=models.CASCADE, related_name="changes")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]

    def __str__(self) -> str:
        return f"Policy change {self.pk} for event policy {self.policy_id}"


class RegistrationStatus(models.TextChoices):
    """Sprint 4. SCRUM-19 adds the waiting list through this field."""

    REGISTERED = "REGISTERED", "Registered"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class Registration(TimeStampedModel):
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.PROTECT, related_name="registrations"
    )
    attendee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registrations"
    )
    status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.REGISTERED
    )
    # SCRUM-21 AC1 - the registration information the attendee gave.
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    accessibility_requirements = models.TextField(blank=True)
    registered_at = models.DateTimeField()

    class Meta:
        ordering = ["registered_at", "pk"]
        constraints = [
            # SCRUM-21 AC3 - one current registration per event and attendee.
            models.UniqueConstraint(
                fields=["event", "attendee"],
                condition=Q(status="REGISTERED"),
                name="one_active_registration_per_attendee",
            ),
        ]

    def __str__(self) -> str:
        return f"Registration {self.pk}: user {self.attendee_id} for event {self.event_id}"


class RegistrationHistory(models.Model):
    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, choices=RegistrationStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=RegistrationStatus.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField()

    class Meta:
        ordering = ["changed_at", "pk"]
        verbose_name_plural = "registration history"

    def __str__(self) -> str:
        return f"Registration {self.registration_id}: {self.from_status or '-'} to {self.to_status}"
