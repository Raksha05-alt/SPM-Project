"""Fixtures for SCRUM-21/81 registration.

``confirmed_event`` is a low-level fixture: an event saved directly as
Confirmed, for registration rules that do not depend on how it was confirmed.
The SCRUM-21 AC4 journey test confirms an event through the real SCRUM-58
action instead.
"""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.registrations.models import RegistrationPolicy
from conftest import _make_user, make_event


@pytest.fixture
def second_attendee(db):
    return _make_user("bea@example.com", Role.ATTENDEE, None, "Bea", "Attendee")


@pytest.fixture
def third_attendee(db):
    return _make_user("cal@example.com", Role.ATTENDEE, None, "Cal", "Attendee")


@pytest.fixture
def confirmed_event(organiser, coordinator):
    return make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Harbour Gala"
    )


def open_policy(event, *, capacity=50, **overrides):
    """Enabled, opened an hour ago, closing in a week."""
    now = timezone.now()
    values = {
        "enabled": True,
        "opens_at": now - datetime.timedelta(hours=1),
        "closes_at": now + datetime.timedelta(days=7),
        "capacity": capacity,
    }
    values.update(overrides)
    return RegistrationPolicy.objects.create(event=event, **values)


def details(user, **overrides):
    data = {
        "full_name": user.get_full_name(),
        "email": user.email,
        "accessibility_requirements": "",
    }
    data.update(overrides)
    return data
