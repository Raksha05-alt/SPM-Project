"""EP-08 to EP-14 - ConnectSphere's venues, their unavailability and bookings."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

WEEKDAYS = list(range(7))  # Monday = 0, matching datetime.weekday()


class LayoutType(TimeStampedModel):
    """Week 7 clarification - room layouts are a catalogue Venue Staff maintain.

    Venues, events, bookings and change requests store the layout ``code``, so a
    layout can be renamed without touching the rows that refer to it. A layout in
    use cannot be deleted; it can be retired (``is_active=False``) instead.
    """

    code = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def layout_label(code: str) -> str:
    """The display name of a layout code, or the code itself if it is unknown."""
    if not code:
        return ""
    found = LayoutType.objects.filter(code=code).values_list("name", flat=True).first()
    return found or code


def every_day():
    return list(WEEKDAYS)


class Venue(TimeStampedModel):
    """SCRUM-65 / SCRUM-5 / SCRUM-9 - one room or space in the catalogue."""

    name = models.CharField(max_length=200, unique=True)
    location = models.CharField(max_length=300, blank=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Free-text facility names, for example "Video conferencing" or "Hearing loop".
    facilities = models.JSONField(default=list, blank=True)
    # Codes from the LayoutType catalogue.
    layouts = models.JSONField(default=list, blank=True)
    wheelchair_access = models.BooleanField(null=True, blank=True)
    accessibility_notes = models.TextField(blank=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    operating_days = models.JSONField(default=every_day, blank=True)
    # Week 7 change 1 - preparation before and reset after every booking. The
    # venue is occupied from (start - setup) to (end + turnaround).
    setup_minutes = models.PositiveIntegerField(default=0)
    turnaround_minutes = models.PositiveIntegerField(default=0)
    # Week 7 change 6 - emergency access and known restrictions the Safety
    # Officer reviews. Maintained by Venue Staff.
    safety_notes = models.TextField(blank=True)
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

    @property
    def setup(self):
        return timezone.timedelta(minutes=self.setup_minutes)

    @property
    def turnaround(self):
        return timezone.timedelta(minutes=self.turnaround_minutes)


class BlockCategory(models.TextChoices):
    """Week 7 change 2 - why a venue is temporarily unavailable."""

    MAINTENANCE = "MAINTENANCE", "Maintenance"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE", "Equipment failure"
    RENOVATION = "RENOVATION", "Renovation"
    SAFETY = "SAFETY", "Safety concern"
    INTERNAL = "INTERNAL", "Internal activity"
    OTHER = "OTHER", "Other operational reason"


class VenueBlock(TimeStampedModel):
    """SCRUM-13 - a period in which Venue Staff have taken a venue out of use."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="blocks")
    start = models.DateTimeField()
    end = models.DateTimeField()
    category = models.CharField(
        max_length=20, choices=BlockCategory.choices, default=BlockCategory.OTHER
    )
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
    # Week 7 change 4 - Venue Staff approved the request as a tentative hold,
    # which the coordinator must confirm before ``hold_expires_at``.
    HELD = "HELD", "Tentatively held"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    RELEASED = "RELEASED", "Released (event cancelled)"
    EXPIRED = "EXPIRED", "Hold expired"
    # Week 7 change 2 - the venue became unavailable after it was booked. The
    # booking is kept on record; the coordinator arranges a replacement.
    DISRUPTED = "DISRUPTED", "Venue unavailable"


# Week 7 clarification - a pending request does not reserve the venue. A
# tentative hold does until it expires, and an approved booking does.
HOLDING_STATUSES = (BookingStatus.HELD, BookingStatus.APPROVED)
# Requests still in play for an event: they can be decided, confirmed or withdrawn.
LIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.HELD, BookingStatus.APPROVED)


def holding_filter(now=None) -> models.Q:
    """Bookings that currently occupy their venue. An expired hold never does."""
    now = now or timezone.now()
    return models.Q(status=BookingStatus.APPROVED) | models.Q(
        status=BookingStatus.HELD, hold_expires_at__gt=now
    )


class VenueBooking(TimeStampedModel):
    """SCRUM-11 / SCRUM-72 - a coordinator's request to use a venue for an event."""

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="venue_bookings"
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()
    attendance = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Week 7 change 3 - which part of the event this venue is for, for example
    # "Main programme" or "Breakout A". An event may have several bookings.
    session_name = models.CharField(max_length=120, blank=True)
    layout = models.CharField(max_length=20, blank=True)
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

    # Week 7 change 4 - a tentative hold and its deadline, set by Venue Staff.
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    hold_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hold_warning_sent_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    # The coordinator confirming a hold turns it into an approved booking.
    hold_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hold_confirmed_at = models.DateTimeField(null=True, blank=True)

    # Week 7 change 2 - when and why the venue became unavailable for this booking.
    disrupted_at = models.DateTimeField(null=True, blank=True)
    disruption_reason = models.TextField(blank=True)
    # The request made to replace this booking after it was disrupted.
    replaced_by = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replaces"
    )

    # SCRUM-59 / SCRUM-66 / SCRUM-70 / SCRUM-80 - an arrangement staff must look at again.
    review_required = models.BooleanField(default=False)
    review_reason = models.TextField(blank=True)
    review_flagged_at = models.DateTimeField(null=True, blank=True)
    # SCRUM-70 AC4 - the period the event has moved to, which staff must look at.
    review_start = models.DateTimeField(null=True, blank=True)
    review_end = models.DateTimeField(null=True, blank=True)
    # SCRUM-80 AC2 / AC3 - the outcome of the last staff review.
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_outcome = models.TextField(blank=True)

    class Meta:
        ordering = ["start", "pk"]
        indexes = [models.Index(fields=["venue", "status", "start"])]

    def __str__(self) -> str:
        return f"{self.venue} for event {self.event_id} ({self.get_status_display()})"

    @property
    def hold_expired(self) -> bool:
        return (
            self.status == BookingStatus.HELD
            and self.hold_expires_at is not None
            and self.hold_expires_at <= timezone.now()
        )

    @property
    def occupied_start(self):
        """Week 7 change 1 - the venue is occupied from the start of setup."""
        return self.start - self.venue.setup

    @property
    def occupied_end(self):
        """...until the end of turnaround."""
        return self.end + self.venue.turnaround


class VenueShortlist(models.Model):
    """SCRUM-68 - venues a coordinator is considering for an event."""

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="venue_shortlist"
    )
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="+")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["event", "venue"], name="unique_shortlisted_venue")
        ]

    def __str__(self) -> str:
        return f"{self.venue} shortlisted for event {self.event_id}"
