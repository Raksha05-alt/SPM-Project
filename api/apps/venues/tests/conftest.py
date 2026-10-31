from datetime import time

import pytest

from apps.accounts.models import Role, User
from apps.venues.models import Venue


def make_venue(**overrides):
    data = {
        "name": "Harbour Hall",
        "location": "Level 2, Marina Wing",
        "capacity": 150,
        "facilities": ["Projector"],
        "layouts": ["THEATRE"],
    }
    data.update(overrides)
    return Venue.objects.create(**data)


@pytest.fixture
def venue(db):
    return make_venue()


@pytest.fixture
def open_venue(venue):
    venue.opens_at = time(8)
    venue.closes_at = time(22)
    venue.save()
    return venue


@pytest.fixture
def tech_staff(db):
    return User.objects.create_user(
        username="tech@connectsphere.example",
        email="tech@connectsphere.example",
        password="pw-for-tests-only",
        role=Role.TECHNICAL_SUPPORT,
    )


@pytest.fixture
def signed_in_venue_staff(api, venue_staff):
    api.force_authenticate(venue_staff)
    return api
