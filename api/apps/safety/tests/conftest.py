"""Fixtures for SCRUM-90: a Planning event and helpers that approve its arrangements.

Venue approval goes through the SCRUM-11 booking contract's
``transition_booking``, the service the SCRUM-72 decision and SCRUM-67
withdrawal actions call, so its AC6 hook runs as it will in those actions.
Equipment rows use the SCRUM-16/77 foundation models directly: the reservation
and amendment actions (G16a/G17) are not on main yet. These fixtures establish
state for service tests; they are not evidence of those user workflows.
"""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
    TechnicalApproval,
)
from apps.events.models import RoomLayout
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import arrangement_version
from apps.venues.bookings import create_booking_record, transition_booking
from apps.venues.models import BookingStatus, Venue
from conftest import _make_user, make_event


@pytest.fixture
def safety_officer(db):
    return _make_user("safety@connectsphere.example", Role.SAFETY_OFFICER, None, "Sam", "Safety")


@pytest.fixture
def second_safety_officer(db):
    return _make_user("safety2@connectsphere.example", Role.SAFETY_OFFICER, None, "Sia", "Safety")


@pytest.fixture
def tech(db):
    return _make_user("tech@connectsphere.example", Role.TECHNICAL_SUPPORT, None, "Tariq", "Tech")


def make_venue(name="Harbour Hall", **overrides):
    data = {
        "name": name,
        "location": "Level 2, Marina Wing",
        "capacity": 200,
        "layouts": [RoomLayout.THEATRE, RoomLayout.BANQUET],
        "facilities": ["Projector"],
        "wheelchair_access": True,
        "accessibility_notes": "Step-free entrance.",
        "opens_at": datetime.time(7),
        "closes_at": datetime.time(23),
    }
    data.update(overrides)
    return Venue.objects.create(**data)


@pytest.fixture
def venue(db):
    return make_venue()


@pytest.fixture
def planning_event(organiser, coordinator, lead):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        supervising_lead=lead,
        required_layout=RoomLayout.THEATRE,
        accessibility_needs="Two wheelchair users.",
    )


def approve_venue(event, venue, approver, *, attendance=120, layout=RoomLayout.THEATRE):
    booking = create_booking_record(
        requested_by=event.coordinator,
        event=event,
        venue=venue,
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
        attendance=attendance,
        layout=layout,
    )
    return transition_booking(booking, BookingStatus.APPROVED, approver)


def approve_equipment(event, tech, *, quantity=2, name="Projector"):
    equipment_type, _ = EquipmentType.objects.get_or_create(
        code=name.upper(), defaults={"name": name, "total_quantity": 10}
    )
    plan, _ = EquipmentPlan.objects.get_or_create(event=event)
    plan.revision += 1
    plan.save(update_fields=["revision"])
    item = EquipmentRequest.objects.create(
        plan=plan,
        equipment_type=equipment_type,
        quantity=quantity,
        technical_requirements="HDMI to both stage screens",
        status=EquipmentRequestStatus.RESERVED,
        requested_by=event.coordinator,
    )
    EquipmentReservation.objects.create(
        request=item,
        quantity=quantity,
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
        reserved_by=tech,
    )
    approval = TechnicalApproval.objects.create(
        plan=plan, plan_revision=plan.revision, approved_by=tech
    )
    return plan, item, approval


@pytest.fixture
def ready_event(planning_event, venue, venue_staff, tech):
    """AC1 - a Planning event whose venue and technical arrangements are all approved."""
    approve_venue(planning_event, venue, venue_staff)
    approve_equipment(planning_event, tech)
    planning_event.refresh_from_db()
    return planning_event


def make_check(event, status=SafetyStatus.PENDING, officer=None, comment=""):
    """A check reviewing the event's current arrangement version.

    G04 tests create checks directly; the request and decision actions that
    create them for real are tested with the G20 workflow.
    """
    decided = status not in (SafetyStatus.PENDING, SafetyStatus.SUPERSEDED)
    return SafetyCheck.objects.create(
        event=event,
        status=status,
        requested_by=event.coordinator,
        arrangement_version=arrangement_version(event),
        decided_by=officer if decided else None,
        decided_at=timezone.now() if decided else None,
        comment=comment,
    )
