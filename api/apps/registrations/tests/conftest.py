"""Fixtures for the registration stories (SCRUM-21, 14, 81, 19, 18)."""

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.registrations.models import Registration, RegistrationStatus
from conftest import make_event


def make_attendee(email, first="Pat", last="Person"):
    return User.objects.create_user(
        username=email,
        email=email,
        password="pw-for-tests-only",
        role=Role.ATTENDEE,
        first_name=first,
        last_name=last,
    )


@pytest.fixture
def as_attendee(api, attendee):
    api.force_authenticate(attendee)
    return api


@pytest.fixture
def event(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        coordinator=coordinator,
        registration_required=True,
        registration_capacity=3,
    )


def details(**overrides):
    data = {"full_name": "Andy Attendee", "email": "attendee@example.com"}
    data.update(overrides)
    return data


def enrol(event, user, status=RegistrationStatus.REGISTERED, **extra):
    now = timezone.now()
    return Registration.objects.create(
        event=event,
        attendee=user,
        full_name=user.get_full_name(),
        email=user.email,
        status=status,
        registered_at=now if status == RegistrationStatus.REGISTERED else None,
        waitlisted_at=now if status == RegistrationStatus.WAITLISTED else None,
        **extra,
    )


def fill(event, count, start=0):
    return [enrol(event, make_attendee(f"filler{start + i}@example.com")) for i in range(count)]
