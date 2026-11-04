from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    ASSIGNMENT = "ASSIGNMENT", "Coordinator assigned"
    APPROVED = "APPROVED", "Request approved"
    CLARIFICATION = "CLARIFICATION", "Clarification requested"
    RESUBMITTED = "RESUBMITTED", "Request resubmitted"
    REJECTED = "REJECTED", "Request rejected"
    # SCRUM-90 - the Operational Safety Check.
    SAFETY_REQUESTED = "SAFETY_REQUESTED", "Safety check requested"
    SAFETY_DECIDED = "SAFETY_DECIDED", "Safety check decided"
    SAFETY_SUPERSEDED = "SAFETY_SUPERSEDED", "Safety check no longer applies"
    PLANNING_REOPENED = "PLANNING_REOPENED", "Event returned to planning"
    # SCRUM-92 - offline clarification notes and resuming review.
    CLARIFICATION_NOTE = "CLARIFICATION_NOTE", "Clarification note added"
    REVIEW_RESUMED = "REVIEW_RESUMED", "Review resumed"
    # SCRUM-11 - a coordinator's venue booking request reaches Venue Staff.
    VENUE_REQUESTED = "VENUE_REQUESTED", "Venue booking requested"
    # SCRUM-72 - Venue Staff approve or reject a venue booking request.
    VENUE_DECIDED = "VENUE_DECIDED", "Venue booking decided"
    VENUE_WITHDRAWN = "VENUE_WITHDRAWN", "Venue booking withdrawn"
    # SCRUM-74 - a coordinator's equipment request reaches Technical Support.
    EQUIPMENT_REQUESTED = "EQUIPMENT_REQUESTED", "Equipment requested"
    EQUIPMENT_UPDATED = "EQUIPMENT_UPDATED", "Equipment arrangement updated"
    EVENT_CANCELLED = "EVENT_CANCELLED", "Event cancelled"
    # SCRUM-58 - an essential resource is unavailable, and the event is confirmed.
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE", "Arrangement unavailable"
    EVENT_CONFIRMED = "EVENT_CONFIRMED", "Event confirmed"
    # SCRUM-79 AC1 (Week 7 change 5) - a submitted request reaches the Lead queue.
    SUBMITTED = "SUBMITTED", "Request submitted"
    # SCRUM-20 - an organiser's change request reaches the coordinator (or Leads).
    CHANGE_REQUESTED = "CHANGE_REQUESTED", "Change requested"
    # SCRUM-21/81 - an attendee's registration, and an event becoming full.
    REGISTERED = "REGISTERED", "Registration confirmed"
    REGISTRATION_FULL = "REGISTRATION_FULL", "Registration full"
    # SCRUM-14/19 - withdrawal, joining the waiting list, and a place opening.
    REG_WITHDRAWN = "REG_WITHDRAWN", "Registration withdrawn"
    WAITLIST_JOINED = "WAITLIST_JOINED", "Joined the waiting list"
    PLACE_AVAILABLE = "PLACE_AVAILABLE", "A place is available"
    # SCRUM-66 - an approved venue no longer suits the event after a change.
    VENUE_REVIEW = "VENUE_REVIEW", "Venue booking needs review"


class NotificationTarget(models.TextChoices):
    """SCRUM-82 - the record a notice points at, beyond its event.

    The screen a notice opens is decided when it is read, from the recipient's
    current access (``apps.notifications.services.destination``); storing a
    target never grants access.
    """

    SAFETY_CHECK = "SAFETY_CHECK", "Safety check"
    VENUE_BOOKING = "VENUE_BOOKING", "Venue booking"


# Assignment notices are unique per occurrence, not per lifetime of an event.
ONE_OFF_KINDS = (NotificationKind.APPROVED, NotificationKind.REJECTED)


class Notification(models.Model):
    """Persistent, recipient-only messages about an event request."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(
        max_length=20, choices=NotificationKind.choices, default=NotificationKind.ASSIGNMENT
    )
    assignment = models.ForeignKey(
        "events.CoordinatorAssignment",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # SCRUM-79/82 - the business occurrence this notice reports (for example
    # "event-status:41" or "assignment:7"). Unique per recipient, so replaying an
    # action never duplicates a notice while a later occurrence still notifies.
    # Blank for notices written before Sprint 4 and by producers not yet moved
    # to ``notify()``.
    occurrence = models.CharField(max_length=120, blank=True, default="")
    target_type = models.CharField(
        max_length=20, choices=NotificationTarget.choices, blank=True, default=""
    )
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    # SCRUM-82 - set the first time the recipient opens the notice.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event", "kind"],
                condition=models.Q(kind__in=ONE_OFF_KINDS),
                name="unique_notification_per_kind",
            ),
            models.UniqueConstraint(
                fields=["recipient", "assignment"], name="unique_assignment_notice_recipient"
            ),
            models.UniqueConstraint(
                fields=["recipient", "occurrence"],
                condition=~models.Q(occurrence=""),
                name="unique_notice_per_recipient_occurrence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["recipient"],
                condition=models.Q(read_at__isnull=True),
                name="notification_unread_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} notification for user {self.recipient_id}, event {self.event_id}"
