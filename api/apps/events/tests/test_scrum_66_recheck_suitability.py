"""SCRUM-66 (US-11.2) - re-check suitability when the event changes."""

import pytest

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


@pytest.fixture
def event(organiser, coordinator):
    # Planning, not confirmed: only a suitability problem should raise a flag.
    return make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=100
    )


@pytest.fixture
def booking(event):
    return book(event, make_venue(capacity=120, layouts=["THEATRE"], wheelchair_access=False))


def patch(client, event, data):
    return client.patch(f"/api/events/{event.pk}/", data, format="json")


@pytest.mark.django_db
def test_ac1_attendance_beyond_capacity_flags_the_booking_and_tells_me(
    signed_in_coordinator, coordinator, event, booking
):
    patch(signed_in_coordinator, event, {"expected_attendance": 180})

    booking.refresh_from_db()
    assert booking.review_required is True
    assert booking.review_reason == (
        "Expected attendance of 180 exceeds the venue's capacity of 120."
    )
    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.REVIEW_NEEDED)
    assert "needs review" in note.message


@pytest.mark.django_db
def test_ac2_an_unsupported_layout_flags_the_booking(signed_in_coordinator, event, booking):
    patch(signed_in_coordinator, event, {"required_layout": "BANQUET"})

    booking.refresh_from_db()
    assert booking.review_required is True
    assert "Banquet" in booking.review_reason


@pytest.mark.django_db
def test_ac2_unsupported_accessibility_needs_flag_the_booking(
    signed_in_coordinator, event, booking
):
    patch(signed_in_coordinator, event, {"accessibility_needs": "Three wheelchair users"})

    booking.refresh_from_db()
    assert booking.review_required is True


@pytest.mark.django_db
def test_ac3_the_reason_is_visible_on_the_event(signed_in_coordinator, event, booking):
    patch(signed_in_coordinator, event, {"expected_attendance": 180})

    [row] = signed_in_coordinator.get("/api/venue-bookings/", {"event": event.pk}).data

    assert row["review_required"] is True
    assert "exceeds the venue's capacity" in row["review_reason"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data", [{"expected_attendance": 110}, {"required_layout": "THEATRE"}, {"name": "Renamed"}]
)
def test_ac4_a_change_that_still_fits_raises_no_flag(signed_in_coordinator, event, booking, data):
    patch(signed_in_coordinator, event, data)

    booking.refresh_from_db()
    assert booking.review_required is False
    assert not Notification.objects.filter(kind=NotificationKind.REVIEW_NEEDED).exists()


@pytest.mark.django_db
def test_only_confirmed_bookings_are_rechecked(signed_in_coordinator, event):
    from apps.venues.models import BookingStatus

    pending = book(event, make_venue(name="Small", capacity=50), status=BookingStatus.PENDING)

    patch(signed_in_coordinator, event, {"expected_attendance": 180})

    pending.refresh_from_db()
    assert pending.review_required is False
