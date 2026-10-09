"""Fixtures for the equipment stories (SCRUM-74, 75, 12, 76, 16, 77)."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequest, EquipmentReservation, EquipmentType
from conftest import make_event


@pytest.fixture
def signed_in_tech(api, tech_staff):
    api.force_authenticate(tech_staff)
    return api


@pytest.fixture
def projector(db):
    return EquipmentType.objects.create(name="Projector", category="AV", total_quantity=10)


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


def make_request(event, equipment_type, quantity=4, **extra):
    return EquipmentRequest.objects.create(
        event=event,
        equipment_type=equipment_type,
        quantity=quantity,
        requested_by=event.coordinator,
        **extra,
    )


def hold(event, equipment_type, quantity, start=None, end=None, **extra):
    """An active reservation for ``event``, with its own request."""
    request = make_request(event, equipment_type, quantity, status="RESERVED")
    return EquipmentReservation.objects.create(
        request=request,
        event=event,
        equipment_type=equipment_type,
        quantity=quantity,
        start=start or event.preferred_start,
        end=end or event.preferred_end,
        **extra,
    )


def another_coordinator(email="c2@connectsphere.example"):
    return User.objects.create_user(
        username=email, email=email, password="pw-for-tests-only", role="COORDINATOR"
    )


HOUR = timezone.timedelta(hours=1)
