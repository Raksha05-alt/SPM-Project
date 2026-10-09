"""SCRUM-73 (US-13.2) - suggest an alternative venue or time when rejecting."""

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.tests.helpers import block, book, iso, make_user
from conftest import make_event, make_venue


def url(booking, step):
    return f"/api/venue-bookings/{booking.pk}/{step}"


@pytest.fixture
def other_venue(db):
    return make_venue(name="Riverside Room")


def reject(client, booking, **suggestion):
    return client.post(
        url(booking, "reject/"), {"reason": "Hall closed", **suggestion}, format="json"
    )


@pytest.mark.django_db
def test_ac1_a_suggested_venue_and_time_go_to_the_coordinator_with_the_rejection(
    signed_in_venue_staff, coordinator, pending, other_venue
):
    start = pending.start + timezone.timedelta(days=1)
    end = pending.end + timezone.timedelta(days=1)

    response = reject(
        signed_in_venue_staff,
        pending,
        suggested_venue=other_venue.pk,
        suggested_start=iso(start),
        suggested_end=iso(end),
        suggestion_note="Same floor, bigger stage",
    )

    assert response.status_code == 200, response.data
    pending.refresh_from_db()
    assert (pending.suggested_venue, pending.suggested_start, pending.suggested_end) == (
        other_venue,
        start,
        end,
    )
    message = Notification.objects.get(recipient=coordinator).message
    assert "Reason: Hall closed" in message
    assert "Suggested alternative: Riverside Room" in message
    assert "Same floor, bigger stage" in message


@pytest.mark.django_db
def test_ac1_a_time_only_suggestion_is_sent(signed_in_venue_staff, coordinator, pending):
    start = pending.start + timezone.timedelta(days=2)

    reject(
        signed_in_venue_staff,
        pending,
        suggested_start=iso(start),
        suggested_end=iso(start + timezone.timedelta(hours=6)),
    )

    pending.refresh_from_db()
    assert pending.suggested_venue is None
    assert "Suggested alternative: " in Notification.objects.get(recipient=coordinator).message


@pytest.mark.django_db
def test_ac1_a_rejection_without_a_suggestion_mentions_none(
    signed_in_venue_staff, coordinator, pending
):
    reject(signed_in_venue_staff, pending)

    assert "Suggested" not in Notification.objects.get(recipient=coordinator).message


@pytest.mark.django_db
def test_ac1_a_suggested_period_must_end_after_it_starts(signed_in_venue_staff, pending):
    response = reject(
        signed_in_venue_staff,
        pending,
        suggested_start=iso(pending.end),
        suggested_end=iso(pending.start),
    )

    assert response.status_code == 400
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_ac2_the_coordinator_sees_the_suggestion_beside_the_reason(
    signed_in_venue_staff, signed_in_coordinator, coordinator, venue_staff, pending, other_venue
):
    signed_in_venue_staff.force_authenticate(venue_staff)
    reject(signed_in_venue_staff, pending, suggested_venue=other_venue.pk)
    signed_in_coordinator.force_authenticate(coordinator)

    [row] = signed_in_coordinator.get("/api/venue-bookings/", {"event": pending.event_id}).data

    assert row["rejection_reason"] == "Hall closed"
    assert row["suggested_venue_name"] == "Riverside Room"


@pytest.mark.django_db
def test_ac3_accepting_creates_a_new_request_with_the_suggested_venue_and_timing(
    api, coordinator, venue_staff, pending, other_venue
):
    start = pending.start + timezone.timedelta(days=1)
    end = pending.end + timezone.timedelta(days=1)
    api.force_authenticate(venue_staff)
    reject(
        api,
        pending,
        suggested_venue=other_venue.pk,
        suggested_start=iso(start),
        suggested_end=iso(end),
    )
    api.force_authenticate(coordinator)

    response = api.post(url(pending, "accept-suggestion/"))

    assert response.status_code == 201, response.data
    new = VenueBooking.objects.get(pk=response.data["id"])
    assert (new.venue, new.start, new.end, new.status) == (
        other_venue,
        start,
        end,
        BookingStatus.PENDING,
    )
    assert (new.attendance, new.layout) == (pending.attendance, pending.layout)
    pending.refresh_from_db()
    assert pending.status == BookingStatus.REJECTED


@pytest.mark.django_db
def test_ac3_accepting_a_time_only_suggestion_keeps_the_original_venue(
    api, coordinator, venue_staff, pending, venue
):
    start = pending.start + timezone.timedelta(days=1)
    api.force_authenticate(venue_staff)
    reject(
        api,
        pending,
        suggested_start=iso(start),
        suggested_end=iso(start + timezone.timedelta(hours=2)),
    )
    api.force_authenticate(coordinator)

    response = api.post(url(pending, "accept-suggestion/"))

    assert response.status_code == 201
    assert response.data["venue"] == venue.pk
    assert response.data["start"] == iso(start)


@pytest.mark.django_db
def test_ac3_there_is_nothing_to_accept_without_a_suggestion(
    api, coordinator, venue_staff, pending
):
    api.force_authenticate(venue_staff)
    reject(api, pending)
    api.force_authenticate(coordinator)

    response = api.post(url(pending, "accept-suggestion/"))

    assert response.status_code == 409
    assert response.data["detail"] == "There is no suggested alternative to accept."


@pytest.mark.django_db
def test_ac3_only_the_assigned_coordinator_can_accept(api, organiser, pending, other_venue):
    pending.status = BookingStatus.REJECTED
    pending.suggested_venue = other_venue
    pending.save()
    api.force_authenticate(make_user("c2@connectsphere.example", Role.EVENT_COORDINATOR))

    response = api.post(url(pending, "accept-suggestion/"))

    assert response.status_code == 403
    assert VenueBooking.objects.count() == 1


@pytest.mark.django_db
def test_ac4_suggesting_a_venue_already_booked_warns_first(
    signed_in_venue_staff, organiser, coordinator, pending, other_venue
):
    rival = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala"
    )
    book(rival, other_venue, pending.start, pending.end)

    warned = reject(signed_in_venue_staff, pending, suggested_venue=other_venue.pk)

    assert warned.status_code == 409
    assert warned.data["warning"] is True
    assert "already booked or blocked" in warned.data["detail"]
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING
    assert not Notification.objects.exists()

    sent = reject(
        signed_in_venue_staff, pending, suggested_venue=other_venue.pk, acknowledge_warning=True
    )

    assert sent.status_code == 200
    pending.refresh_from_db()
    assert pending.suggested_venue == other_venue


@pytest.mark.django_db
def test_ac4_suggesting_a_blocked_venue_warns_first(signed_in_venue_staff, pending, other_venue):
    block(other_venue, pending.start, pending.end)

    response = reject(signed_in_venue_staff, pending, suggested_venue=other_venue.pk)

    assert response.status_code == 409


@pytest.mark.django_db
def test_ac4_suggesting_a_new_time_at_the_same_venue_also_checks_it(
    signed_in_venue_staff, organiser, coordinator, pending, venue
):
    later = pending.start + timezone.timedelta(days=3)
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    book(rival, venue, later, later + timezone.timedelta(hours=2))

    response = reject(
        signed_in_venue_staff,
        pending,
        suggested_start=iso(later),
        suggested_end=iso(later + timezone.timedelta(hours=1)),
    )

    assert response.status_code == 409
