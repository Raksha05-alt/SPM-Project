"""The seed command has to stay runnable, because demos and manual testing use it."""

import pytest
from django.core.management import call_command

from apps.accounts.models import Role, User
from apps.events.models import EventRequest


@pytest.mark.django_db
def test_seeding_creates_one_user_per_role_and_some_events():
    call_command("seed_demo_data")

    assert User.objects.count() == 6
    assert set(User.objects.values_list("role", flat=True)) == set(Role.values)
    assert EventRequest.objects.count() == 3


@pytest.mark.django_db
def test_seeding_twice_does_not_duplicate_anything():
    call_command("seed_demo_data")
    call_command("seed_demo_data")

    assert User.objects.count() == 6
    assert EventRequest.objects.count() == 3
