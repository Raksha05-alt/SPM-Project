"""EP-08 to EP-14 - ConnectSphere's venues, their unavailability and bookings."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.events.models import RoomLayout

WEEKDAYS = list(range(7))  # Monday = 0, matching datetime.weekday()


def every_day():
    return list(WEEKDAYS)


class Venue(TimeStampedModel):
    """SCRUM-65 / SCRUM-5 / SCRUM-9 - one room or space in the catalogue."""

    name = models.CharField(max_length=200, unique=True)
    location = models.CharField(max_length=300, blank=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Free-text facility names, for example "Video conferencing" or "Hearing loop".
    facilities = models.JSONField(default=list, blank=True)
    # Values from RoomLayout.
    layouts = models.JSONField(default=list, blank=True)
    wheelchair_access = models.BooleanField(null=True, blank=True)
    accessibility_notes = models.TextField(blank=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    operating_days = models.JSONField(default=every_day, blank=True)
    # Operational status: an inactive venue is out of service until staff reopen it.
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def active_blocks(self):
        return self.blocks.filter(removed_at__isnull=True)

    def is_blocked_at(self, moment=None) -> bool:
        moment = moment or timezone.now()
        return self.active_blocks().filter(start__lte=moment, end__gt=moment).exists()


class VenueBlock(TimeStampedModel):
    """SCRUM-13 - a period in which Venue Staff have taken a venue out of use."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="blocks")
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=300)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # A removed block is kept, so that who removed it and when stays on record.
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["start"]

    def __str__(self) -> str:
        return f"{self.venue} blocked {self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}"


class BookingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    RELEASED = "RELEASED", "Released (event cancelled)"


# A pending request tentatively holds the period; an approved one confirms it.
HOLDING_STATUSES = (BookingStatus.PENDING, BookingStatus.APPROVED)


class VenueBooking(TimeStampedModel):
    """SCRUM-11 / SCRUM-72 - a coordinator's request to use a venue for an event."""

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="venue_bookings"
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()
    attendance = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    layout = models.CharField(max_length=20, choices=RoomLayout.choices, blank=True)
    facilities = models.JSONField(default=list, blank=True)
    accessibility_needs = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.PENDING
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # SCRUM-73 - an alternative Venue Staff suggest when they reject.
    suggested_venue = models.ForeignKey(
        Venue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    suggested_start = models.DateTimeField(null=True, blank=True)
    suggested_end = models.DateTimeField(null=True, blank=True)
    suggestion_note = models.TextField(blank=True)

    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    # SCRUM-59 / SCRUM-66 / SCRUM-70 / SCRUM-80 - an arrangement staff must look at again.
    review_required = models.BooleanField(default=False)
    review_reason = models.TextField(blank=True)
    review_flagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["start", "pk"]
        indexes = [models.Index(fields=["venue", "status", "start"])]

    def __str__(self) -> str:
        return f"{self.venue} for event {self.event_id} ({self.get_status_display()})"
