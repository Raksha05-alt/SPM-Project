"""SCRUM-65 - ConnectSphere's venue records."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel

WEEKDAYS = list(range(7))  # Monday = 0, matching datetime.weekday()


def every_day():
    return list(WEEKDAYS)


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
    # Values from apps.events.models.RoomLayout.
    layouts = models.JSONField(default=list, blank=True)
    wheelchair_access = models.BooleanField(null=True, blank=True)
    accessibility_notes = models.TextField(blank=True)
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
