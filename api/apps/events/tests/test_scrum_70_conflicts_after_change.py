"""SCRUM-70 (US-14.2) - flag venue conflicts caused by a confirmed-event change."""

import pytest

from apps.core.statuses import EventStatus
from apps.events.tests.change_helpers import DAY, HOUR, confirmed_event, iso
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import block, book
from conftest import make_event


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


def move(client, event, delta):
    return client.patch(
        f"/api/events/{event.pk}/",
        {
            "preferred_start": iso(event.preferred_start + delta),
            "preferred_end": iso(event.preferred_end + delta),
        },
        format="json",
    )


@pytest.mark.django_db
def test_ac1_a_new_time_that_overlaps_another_confirmed_booking_is_flagged(
    signed_in_coordinator, organiser, coordinator, setup
):
    event, booking, _, _ = setup
    rival = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala"
    )
    book(rival, booking.venue, event.preferred_start + DAY, event.preferred_end + DAY)

    move(signed_in_coordinator, event, DAY)

    booking.refresh_from_db()
    assert booking.review_required is True
    assert "overlaps Gala" in booking.review_reason


@pytest.mark.django_db
def test_ac1_a_new_time_inside_a_venue_block_is_flagged(signed_in_coordinator, setup):
    event, booking, _, _ = setup
    block(booking.venue, event.preferred_start + DAY, event.preferred_end + DAY, reason="Repairs")

    move(signed_in_coordinator, event, DAY)

    booking.refresh_from_db()
    assert "Blocked: Repairs" in booking.review_reason


@pytest.mark.django_db
def test_ac2_the_current_booking_is_kept_while_staff_review_it(signed_in_coordinator, setup):
    event, booking, _, _ = setup
    original = (booking.start, booking.end)

    move(signed_in_coordinator, event, DAY)

    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert (booking.start, booking.end) == original
    assert (booking.review_start, booking.review_end) == (original[0] + DAY, original[1] + DAY)


@pytest.mark.django_db
def test_ac3_no_conflict_keeps_the_booking_and_records_the_check(signed_in_coordinator, setup):
    event, booking, _, _ = setup

    move(signed_in_coordinator, event, 2 * HOUR)

    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert "has no conflicting bookings" in booking.review_reason


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", ["coordinator", "venue_staff"])
def test_ac4_staff_and_coordinator_see_the_reason_and_period(
    request, api, setup, coordinator, viewer
):
    event = setup[0]
    api.force_authenticate(coordinator)
    move(api, event, DAY)
    api.force_authenticate(request.getfixturevalue(viewer))

    [row] = api.get("/api/venue-bookings/", {"event": event.pk}).data

    assert row["review_required"] is True
    assert row["review_reason"]
    assert row["review_start"] and row["review_end"]


@pytest.mark.django_db
def test_a_planning_event_moved_without_conflict_raises_no_flag(
    signed_in_coordinator, organiser, coordinator
):
    from conftest import make_venue

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    booking = book(event, make_venue())

    move(signed_in_coordinator, event, HOUR)

    booking.refresh_from_db()
    assert booking.review_required is False


@pytest.mark.django_db
def test_a_shortened_event_reviews_the_whole_new_period(signed_in_coordinator, setup):
    event, booking, _, _ = setup
    new_start = event.preferred_start + 5 * HOUR
    signed_in_coordinator.patch(
        f"/api/events/{event.pk}/",
        {"preferred_start": iso(new_start), "preferred_end": iso(new_start + HOUR)},
        format="json",
    )

    booking.refresh_from_db()
    assert booking.review_start == new_start
    assert booking.review_end == new_start + HOUR
