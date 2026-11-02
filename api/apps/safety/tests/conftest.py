"""Fixtures for SCRUM-90: a Planning event and helpers that approve its arrangements.

G20: arrangements are approved through the real actions on main - the
coordinator requests the venue (SCRUM-11 ``request_booking``) and Venue Staff
approve it (SCRUM-72 ``approve_booking``); the coordinator requests equipment
(SCRUM-74 ``create_request``) and Technical Support reserve it (SCRUM-16
``reserve``, which approves the plan once everything is reserved). Each action
runs its own Safety invalidation hook, as it does for users.
"""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentType
from apps.equipment.reservations import reserve
from apps.equipment.services import create_request
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import arrangement_version
from apps.venues.bookings import approve_booking, request_booking
from apps.venues.models import Venue
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
        # SCRUM-91: layouts are catalogue codes (seeded THEATRE and BANQUET).
        "layouts": ["THEATRE", "BANQUET"],
        "facilities": ["Projector"],
        "wheelchair_access": True,
        "accessibility_notes": "Step-free entrance.",
        "emergency_access": "Two fire exits to the stairwell; assembly at the promenade.",
        "known_restrictions": "No open flames. Stage load limit 500 kg.",
        "opens_at": datetime.time(7),
        "closes_at": datetime.time(23),
    }
    data.update(overrides)
    return Venue.objects.create(**data)


@pytest.fixture
def venue(db):
    return make_venue()


def daytime_period(days_ahead=30):
    """09:00-15:00 Singapore time, inside the venue's hours, so the real booking
    action accepts it whatever time of day the suite runs."""
    day = timezone.localdate() + datetime.timedelta(days=days_ahead)
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time(9)))
    return start, start + datetime.timedelta(hours=6)


@pytest.fixture
def planning_event(organiser, coordinator, lead):
    start, end = daytime_period()
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        supervising_lead=lead,
        required_layout="THEATRE",
        accessibility_needs="Two wheelchair users.",
        preferred_start=start,
        preferred_end=end,
    )


def approve_venue(event, venue, approver, *, attendance=120, layout="THEATRE"):
    """The coordinator requests the venue and Venue Staff approve it (real actions)."""
    booking = request_booking(
        event=event,
        venue=venue,
        requested_by=event.coordinator,
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
        attendance=attendance,
        layout=layout,
    )
    return approve_booking(booking, approver)


def approve_equipment(event, tech, *, quantity=2, name="Projector"):
    """The coordinator requests equipment and Technical Support reserve it.

    ``reserve`` approves the technical plan itself once every line is reserved.
    """
    equipment_type, _ = EquipmentType.objects.get_or_create(
        code=name.upper(), defaults={"name": name, "total_quantity": 10}
    )
    item = create_request(
        event=event,
        requested_by=event.coordinator,
        equipment_type=equipment_type.pk,
        quantity=quantity,
        technical_requirements="HDMI to both stage screens",
    )
    item.refresh_from_db()
    reserve(equipment_request=item, actor=tech, expected_revision=item.plan.revision)
    plan = item.plan
    plan.refresh_from_db()
    item.refresh_from_db()
    return plan, item, plan.technical_approvals.order_by("-pk").first()


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
