"""SCRUM-65 - ConnectSphere's venue records."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

WEEKDAYS = list(range(7))  # Monday = 0, matching datetime.weekday()


def every_day():
    return list(WEEKDAYS)


class LayoutType(TimeStampedModel):
    """SCRUM-91 - one entry in the room layout catalogue that Venue Staff maintain.

    Venues, event requests and venue bookings store the layout ``code``. The code
    never changes once created; the name and description can. A retired layout
    stays readable on the records that already use it but cannot be newly chosen.
    """

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["sort_order", "name", "pk"]
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"), name="layout_type_unique_name_ignoring_case"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class VenueQuerySet(models.QuerySet):
    def supporting_layout(self, layout: str):
        """SCRUM-5 AC3 - venues that have recorded this layout as supported.

        This is the shared eligibility rule for coordinator venue search
        (SCRUM-64): a venue with the layout recorded may appear in the results.
        """
        return self.filter(layouts__contains=[layout])


class Venue(TimeStampedModel):
    """One room or space ConnectSphere operates."""

    name = models.CharField(max_length=200, unique=True)
    location = models.CharField(max_length=300, blank=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Free-text facility names, for example "Video conferencing" or "Hearing loop".
    facilities = models.JSONField(default=list, blank=True)
    # LayoutType codes (SCRUM-91 catalogue).
    layouts = models.JSONField(default=list, blank=True)
    wheelchair_access = models.BooleanField(null=True, blank=True)
    accessibility_notes = models.TextField(blank=True)
    # SCRUM-90 AC2 - what the Safety Officer reviews before an event is confirmed.
    emergency_access = models.TextField(
        blank=True, help_text="Emergency exits, evacuation routes and assembly points."
    )
    known_restrictions = models.TextField(
        blank=True, help_text="Known safety restrictions, such as load limits or no open flames."
    )
    setup_minutes = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    turnaround_minutes = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    operating_days = models.JSONField(default=every_day, blank=True)
    # SCRUM-9 AC4 - the venue's current operational status.
    in_service = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = VenueQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VenueBlock(TimeStampedModel):
    """A half-open [starts_at, ends_at) period of unavailability."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="blocks")
    reason = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        ordering = ["starts_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="venue_block_positive_interval",
            )
        ]

    def __str__(self):
        return f"{self.venue_id}: {self.reason}"


class VenueBlockHistory(models.Model):
    """Durable snapshots, including removals; written with the block transaction."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="block_history")
    block_id = models.PositiveBigIntegerField()
    action = models.CharField(
        max_length=10, choices=[(x, x) for x in ("created", "updated", "removed")]
    )
    reason = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Block {self.block_id} {self.action} at {self.created_at}"


class VenueShortlistEntry(TimeStampedModel):
    """SCRUM-68: a venue and the search criteria saved for one event."""

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="venue_shortlist"
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="shortlist_entries")
    search_criteria = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["event", "venue"], name="unique_event_shortlist_venue")
        ]


class BookingStatus(models.TextChoices):
    """SCRUM-11 booking contract - the Sprint 3 booking states.

    Sprint 4 adds Held, Expired and Disrupted (SCRUM-85/86/88) through this
    same field and the transition map in apps.venues.bookings. A booking's status
    is separate from its event's status: an Approved booking does not mean the
    event has passed Safety review or been Confirmed.
    """

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


# Only an Approved booking reserves the venue. Pending, Rejected and Withdrawn
# requests do not occupy it (Sprint 3 occupancy contract).
OCCUPYING_BOOKING_STATUSES = frozenset({BookingStatus.APPROVED})


class VenueBookingQuerySet(models.QuerySet):
    def occupying(self):
        return self.filter(status__in=OCCUPYING_BOOKING_STATUSES)

    def overlapping(self, starts_at, ends_at):
        """Half-open [start, end): a booking ending at 10:00 does not overlap a 10:00 start."""
        return self.filter(starts_at__lt=ends_at, ends_at__gt=starts_at)


class SessionKind(models.TextChoices):
    MAIN = "MAIN", "Main programme"
    BREAKOUT = "BREAKOUT", "Breakout"


class EventSession(TimeStampedModel):
    """Stable identity across requests, decisions, withdrawal and replacement.

    Period and requirements are stored on each booking revision; MAIN attendance
    follows the event, while BREAKOUT attendance belongs to that booking.
    """

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.PROTECT, related_name="venue_sessions"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=SessionKind.choices)
    is_active = models.BooleanField(default=True)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["event", "name"], name="event_session_unique_name"),
            models.UniqueConstraint(
                fields=["event"],
                condition=models.Q(kind="MAIN"),
                name="event_session_one_main",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="MAIN") | models.Q(is_active=True, is_required=True),
                name="event_session_main_required",
            ),
        ]


class VenueBooking(TimeStampedModel):
    """SCRUM-11 - a coordinator's request to book one venue for one event period.

    Requests are kept after rejection or withdrawal; a later request for the
    same event and venue is a new row, so earlier decisions are never overwritten.
    """

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.PROTECT, related_name="venue_bookings"
    )
    session = models.ForeignKey(EventSession, on_delete=models.PROTECT, related_name="bookings")
    replaces = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacements"
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="bookings")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    attendance = models.PositiveIntegerField()
    # A LayoutType code (SCRUM-91 catalogue); blank means no layout preference.
    layout = models.CharField(max_length=20, blank=True)
    # Facility names, normalised as venue facilities are.
    required_facilities = models.JSONField(default=list, blank=True)
    wheelchair_access_required = models.BooleanField(default=False)
    # Kept for Venue Staff to read; not interpreted automatically.
    accessibility_notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.PENDING
    )
    status_changed_at = models.DateTimeField(default=timezone.now)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    # Venue Staff decision (SCRUM-72).
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)

    objects = VenueBookingQuerySet.as_manager()

    class Meta:
        ordering = ["-requested_at", "-pk"]
        indexes = [models.Index(fields=["venue", "status", "starts_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="venue_booking_positive_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(attendance__gte=1),
                name="venue_booking_attendance_at_least_one",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=BookingStatus.REJECTED) | ~models.Q(decision_reason=""),
                name="venue_booking_rejection_has_reason",
            ),
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(status=BookingStatus.APPROVED),
                name="venue_booking_one_approved_per_session",
            ),
        ]

    def save(self, *args, **kwargs):
        # Compatibility for existing internal fixture/import writers. Production
        # actions resolve a session under the event lock before writing.
        if not self.session_id:
            self.session, _ = EventSession.objects.get_or_create(
                event_id=self.event_id,
                kind=SessionKind.MAIN,
                defaults={"name": "Main programme"},
            )
        if self.session.event_id != self.event_id:
            raise ValueError("The booking session must belong to its event.")
        super().save(*args, **kwargs)

    @property
    def effective_attendance(self):
        if self.session.kind == SessionKind.MAIN:
            return self.event.expected_attendance
        return self.attendance

    def __str__(self) -> str:
        return f"Booking {self.pk}: event {self.event_id} at venue {self.venue_id} [{self.status}]"


class VenueBookingHistory(models.Model):
    """Every status change of a booking, with who made it, when and why. Never edited."""

    booking = models.ForeignKey(VenueBooking, on_delete=models.PROTECT, related_name="history")
    from_status = models.CharField(max_length=20, choices=BookingStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=BookingStatus.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at", "pk"]
        verbose_name_plural = "venue booking history"

    def __str__(self) -> str:
        return f"Booking {self.booking_id}: {self.from_status or 'new'} -> {self.to_status}"
