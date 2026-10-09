"""Fixtures shared by the venue booking decision tests (SCRUM-72, 73, 67, 69).

Test modules that define their own ``event`` fixture override the one here.
"""

import pytest

from apps.core.statuses import EventStatus
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book
from conftest import make_event


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


@pytest.fixture
def pending(event, venue, coordinator):
    return book(event, venue, status=BookingStatus.PENDING, requested_by=coordinator)


@pytest.fixture
def approved(event, venue, coordinator):
    return book(event, venue, status=BookingStatus.APPROVED, requested_by=coordinator)
