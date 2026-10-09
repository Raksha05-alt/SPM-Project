"""Small behaviours not tied to a single acceptance criterion."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.venues.availability import segments
from apps.venues.models import VenueShortlist
from apps.venues.tests.helpers import block, book
from conftest import future_at, make_event, make_venue


@pytest.mark.django_db
def test_venue_records_describe_themselves(organiser, venue):
    event = make_event(organiser, status=EventStatus.PLANNING)
    start = future_at(3, 9)
    held = block(venue, start, start + timezone.timedelta(days=1))
    booking = book(event, venue)
    entry = VenueShortlist.objects.create(event=event, venue=venue)

    assert str(venue) == "Harbour Hall"
    assert str(held).startswith("Harbour Hall blocked ")
    assert str(booking) == f"Harbour Hall for event {event.pk} (Approved)"
    assert str(entry) == f"Harbour Hall shortlisted for event {event.pk}"


@pytest.mark.django_db
def test_back_to_back_blocks_with_the_same_reason_show_as_one_period(venue):
    start = future_at(3, 9)
    middle = start + timezone.timedelta(hours=2)
    end = middle + timezone.timedelta(hours=2)
    block(venue, start, middle, reason="Repairs")
    block(venue, middle, end, reason="Repairs")

    [piece] = segments(venue, start, end)

    assert (piece["status"], piece["start"], piece["end"]) == ("BLOCKED", start, end)


@pytest.mark.django_db
@pytest.mark.parametrize("capacity", [0, -5])
def test_capacity_errors_are_in_plain_words(signed_in_venue_staff, capacity):
    response = signed_in_venue_staff.post(
        "/api/venues/", {"name": "New", "capacity": capacity}, format="json"
    )

    assert response.data["capacity"] == ["Capacity must be at least one person."]


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["", "   "])
def test_a_block_without_a_reason_says_why_it_is_refused(signed_in_venue_staff, reason):
    venue = make_venue()
    start = future_at(3, 9)

    response = signed_in_venue_staff.post(
        f"/api/venues/{venue.pk}/blocks/",
        {
            "start": start.isoformat(),
            "end": (start + timezone.timedelta(hours=1)).isoformat(),
            "reason": reason,
        },
        format="json",
    )

    assert response.data["reason"] == ["Say why the venue is unavailable."]
