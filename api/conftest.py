"""Shared pytest fixtures.

Every test that touches the database asks for one of these rather than building
users inline, so that adding a field to User does not break thirty tests.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import ClientOrganisation, Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest

PASSWORD = "Sprint1-Test-Passw0rd"


def _make_user(email, role, organisation=None, first="Test", last="User"):
    return User.objects.create_user(
        username=email,
        email=email,
        password=PASSWORD,
        role=role,
        organisation=organisation,
        first_name=first,
        last_name=last,
    )


@pytest.fixture(autouse=True)
def _layout_catalogue(request):
    """SCRUM-91 - make sure the seeded room layout catalogue exists in database tests.

    Migration 0006 seeds it, but a ``transaction=True`` test empties every table
    afterwards, which would leave later tests without any layouts.
    """
    marker = request.node.get_closest_marker("django_db")
    uses_db = marker is not None or {"db", "transactional_db"} & set(request.fixturenames)
    if not uses_db:
        return
    transactional = (marker is not None and marker.kwargs.get("transaction")) or (
        "transactional_db" in request.fixturenames
    )
    request.getfixturevalue("transactional_db" if transactional else "db")
    from apps.venues.layouts import ensure_seed_layouts

    ensure_seed_layouts()


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def acme(db):
    return ClientOrganisation.objects.create(name="Acme Pte Ltd", contact_email="ops@acme.example")


@pytest.fixture
def globex(db):
    return ClientOrganisation.objects.create(name="Globex LLP", contact_email="ops@globex.example")


@pytest.fixture
def organiser(db, acme):
    return _make_user("organiser@acme.example", Role.EVENT_ORGANISER, acme, "Ada", "Organiser")


@pytest.fixture
def other_organiser(db, globex):
    return _make_user("organiser@globex.example", Role.EVENT_ORGANISER, globex, "Otto", "Other")


@pytest.fixture
def coordinator(db):
    return _make_user(
        "coordinator@connectsphere.example", Role.EVENT_COORDINATOR, None, "Cora", "Coordinator"
    )


@pytest.fixture
def venue_staff(db):
    return _make_user("venue@connectsphere.example", Role.VENUE_STAFF, None, "Vera", "Venue")


@pytest.fixture
def lead(db):
    return _make_user(
        "lead@connectsphere.example", Role.EVENT_COORDINATOR_LEAD, first="Lee", last="Lead"
    )


@pytest.fixture
def second_coordinator(db):
    return _make_user(
        "second@connectsphere.example", Role.EVENT_COORDINATOR, first="Casey", last="Coordinator"
    )


@pytest.fixture
def attendee(db):
    return _make_user("attendee@example.com", Role.ATTENDEE, None, "Andy", "Attendee")


@pytest.fixture
def signed_in_organiser(api, organiser):
    api.force_authenticate(organiser)
    return api


@pytest.fixture
def signed_in_coordinator(api, coordinator):
    api.force_authenticate(coordinator)
    return api


def make_event(organiser, *, complete=True, status=EventStatus.DRAFT, **overrides):
    start = timezone.now() + timezone.timedelta(days=30)
    data = {
        "organisation": organiser.organisation,
        "created_by": organiser,
        "status": status,
        "name": "Regional Partner Conference" if complete else "",
        "purpose": "Annual partner briefing" if complete else "",
        "preferred_start": start if complete else None,
        "preferred_end": start + timezone.timedelta(hours=6) if complete else None,
        "expected_attendance": 120 if complete else None,
    }
    data.update(overrides)
    if status != EventStatus.DRAFT and "submitted_at" not in overrides:
        data["submitted_at"] = timezone.now()
    return EventRequest.objects.create(**data)


@pytest.fixture
def complete_draft(organiser):
    return make_event(organiser, complete=True)


@pytest.fixture
def incomplete_draft(organiser):
    return make_event(organiser, complete=False)


@pytest.fixture
def submitted_event(organiser):
    return make_event(organiser, complete=True, status=EventStatus.SUBMITTED)
