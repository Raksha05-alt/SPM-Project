"""Shared set-up for the change stories (SCRUM-59, 66, 70, 20, 78, 80, 18)."""

from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentType
from apps.equipment.tests.conftest import hold
from apps.registrations.tests.conftest import enrol, make_attendee
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue

HOUR = timezone.timedelta(hours=1)
DAY = timezone.timedelta(days=1)


def confirmed_event(organiser, coordinator, **overrides):
    """A confirmed event with an approved venue, reserved equipment and an attendee."""
    event = make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        coordinator=coordinator,
        registration_required=True,
        **overrides,
    )
    venue = make_venue(capacity=150)
    booking = book(event, venue)
    projector = EquipmentType.objects.create(name="Projector", total_quantity=5)
    reservation = hold(event, projector, 3)
    attendee = make_attendee("guest@example.com", "Gina", "Guest")
    enrol(event, attendee)
    return event, booking, reservation.request, attendee


def iso(moment):
    return moment.isoformat()
