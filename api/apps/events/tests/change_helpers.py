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


PROPOSED = {
    "preferred_start": "proposed_start",
    "preferred_end": "proposed_end",
    "expected_attendance": "proposed_attendance",
    "required_layout": "proposed_layout",
    "accessibility_needs": "proposed_accessibility_needs",
    "equipment_notes": "proposed_equipment_notes",
}


def approve_change(api, event, data, *, organiser=None, coordinator=None):
    """Week 7 clarification - a confirmed event changes only through a change request.

    The client raises the request with ``data`` (event field names), the assigned
    coordinator approves it, and the approved change is applied. Returns the
    approval response.
    """
    organiser = organiser or event.created_by
    coordinator = coordinator or event.coordinator
    api.force_authenticate(organiser)
    proposal = {PROPOSED[field]: value for field, value in data.items()}
    raised = api.post(
        f"/api/events/{event.pk}/change-requests/",
        {"description": "Requested change", **proposal},
        format="json",
    )
    assert raised.status_code == 201, raised.data
    api.force_authenticate(coordinator)
    decided = api.post(
        f"/api/change-requests/{raised.data['id']}/approve/", {"reason": "Agreed"}, format="json"
    )
    assert decided.status_code == 200, decided.data
    event.refresh_from_db()
    return decided
