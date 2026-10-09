"""SCRUM-69 (US-14.1) - prevent overlapping bookings for the same venue."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book, booking_payload, iso
from conftest import make_event

HOUR = timezone.timedelta(hours=1)


@pytest.fixture
def rival(organiser, coordinator):
    return make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Board Dinner"
    )


@pytest.fixture
def confirmed(rival, venue, event):
    return book(rival, venue, event.preferred_start, event.preferred_start + 2 * HOUR)


def request(client, event, venue, start, end):
    return client.post(
        "/api/venue-bookings/",
        booking_payload(event, venue, start=iso(start), end=iso(end)),
        format="json",
    )


@pytest.mark.django_db
def test_ac1_an_overlapping_request_is_flagged_and_names_the_other_event(
    signed_in_coordinator, event, venue, confirmed
):
    response = request(
        signed_in_coordinator, event, venue, confirmed.start + HOUR, confirmed.end + HOUR
    )

    assert response.status_code == 201
    [conflict] = response.data["conflicts"]
    assert (conflict["event_name"], conflict["booking"]) == ("Board Dinner", confirmed.pk)


@pytest.mark.django_db
def test_ac2_back_to_back_bookings_do_not_conflict(signed_in_coordinator, event, venue, confirmed):
    before = request(
        signed_in_coordinator, event, venue, confirmed.start - 2 * HOUR, confirmed.start
    )
    after = request(signed_in_coordinator, event, venue, confirmed.end, confirmed.end + HOUR)

    assert before.data["conflicts"] == []
    assert after.data["conflicts"] == []


@pytest.mark.django_db
def test_ac3_approval_is_refused_while_the_conflict_remains(
    signed_in_venue_staff, event, venue, confirmed
):
    clash = book(event, venue, confirmed.start, confirmed.end, status=BookingStatus.PENDING)

    response = signed_in_venue_staff.post(f"/api/venue-bookings/{clash.pk}/approve/")

    assert response.status_code == 409
    assert response.data["conflicts"][0]["event_name"] == "Board Dinner"
    clash.refresh_from_db()
    assert clash.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_ac4_cancelling_the_conflicting_event_clears_the_conflict(
    api, coordinator, venue_staff, event, venue, rival, confirmed
):
    clash = book(event, venue, confirmed.start, confirmed.end, status=BookingStatus.PENDING)
    api.force_authenticate(coordinator)
    cancelled = api.post(f"/api/events/{rival.pk}/cancel/", {"reason": "Postponed"}, format="json")
    assert cancelled.status_code == 200, cancelled.data
    confirmed.refresh_from_db()
    assert confirmed.status == BookingStatus.RELEASED
    assert api.get(f"/api/venue-bookings/{clash.pk}/").data["conflicts"] == []

    api.force_authenticate(venue_staff)
    approved = api.post(f"/api/venue-bookings/{clash.pk}/approve/")

    assert approved.status_code == 200


@pytest.mark.django_db
def test_ac5_approving_the_first_of_two_requests_flags_the_second(
    signed_in_venue_staff, organiser, coordinator, event, venue
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator, name="Expo")
    first = book(event, venue, status=BookingStatus.PENDING)
    second = book(other, venue, status=BookingStatus.PENDING)
    assert signed_in_venue_staff.get(f"/api/venue-bookings/{second.pk}/").data["conflicts"] == []

    signed_in_venue_staff.post(f"/api/venue-bookings/{first.pk}/approve/")

    [conflict] = signed_in_venue_staff.get(f"/api/venue-bookings/{second.pk}/").data["conflicts"]
    assert conflict["event_name"] == "Regional Partner Conference"
    assert (
        signed_in_venue_staff.post(f"/api/venue-bookings/{second.pk}/approve/").status_code == 409
    )


@pytest.mark.django_db
def test_other_bookings_of_the_same_event_are_not_conflicts(signed_in_coordinator, event, venue):
    book(event, venue)

    response = request(
        signed_in_coordinator, event, venue, event.preferred_start, event.preferred_end
    )

    assert response.data["conflicts"] == []


@pytest.mark.django_db
def test_a_different_venue_never_conflicts(signed_in_coordinator, event, confirmed):
    from conftest import make_venue

    elsewhere = make_venue(name="Elsewhere")

    response = request(signed_in_coordinator, event, elsewhere, confirmed.start, confirmed.end)

    assert response.data["conflicts"] == []
