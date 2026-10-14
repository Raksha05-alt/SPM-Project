from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from apps.core.models import TimeStampedModel


class Role(models.TextChoices):
    """The five roles of the customer briefing, plus the two internal roles added
    by the Week 7 customer changes (Event Coordinator Lead, Safety Officer)."""

    EVENT_ORGANISER = "ORGANISER", "Event Organiser"
    EVENT_COORDINATOR = "COORDINATOR", "Event Coordinator"
    COORDINATOR_LEAD = "COORDINATOR_LEAD", "Event Coordinator Lead"
    SAFETY_OFFICER = "SAFETY_OFFICER", "Safety Officer"
    VENUE_STAFF = "VENUE_STAFF", "Venue Staff"
    TECHNICAL_SUPPORT = "TECH_SUPPORT", "Technical Support Staff"
    ATTENDEE = "ATTENDEE", "Attendee"


INTERNAL_ROLES = frozenset(
    {
        Role.EVENT_COORDINATOR,
        Role.COORDINATOR_LEAD,
        Role.VENUE_STAFF,
        Role.TECHNICAL_SUPPORT,
        Role.SAFETY_OFFICER,
    }
)

# US-01.1 AC1/AC2 - where each role lands after signing in.
LANDING_PATHS = {
    Role.EVENT_ORGANISER: "/organiser",
    Role.EVENT_COORDINATOR: "/coordinator",
    Role.COORDINATOR_LEAD: "/lead",
    Role.VENUE_STAFF: "/venues",
    Role.TECHNICAL_SUPPORT: "/equipment",
    Role.ATTENDEE: "/events",
    Role.SAFETY_OFFICER: "/safety",
}


class ClientOrganisation(TimeStampedModel):
    name = models.CharField(max_length=200, unique=True)
    contact_email = models.EmailField()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ATTENDEE)
    coordinator_available = models.BooleanField(
        default=True,
        help_text="Shown to Event Coordinator Leads when they choose who to assign (coordinators only).",
    )
    organisation = models.ForeignKey(
        ClientOrganisation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} <{self.email}>"

    @property
    def landing_path(self) -> str:
        return LANDING_PATHS[self.role]

    @property
    def is_internal(self) -> bool:
        return self.role in INTERNAL_ROLES

    @property
    def is_organiser(self) -> bool:
        return self.role == Role.EVENT_ORGANISER

    @property
    def is_coordinator(self) -> bool:
        return self.role == Role.EVENT_COORDINATOR

    @property
    def is_lead(self) -> bool:
        return self.role == Role.COORDINATOR_LEAD

    @property
    def is_safety_officer(self) -> bool:
        return self.role == Role.SAFETY_OFFICER
