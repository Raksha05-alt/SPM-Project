"""SCRUM-86: actual staff block and coordinator replacement actions."""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.safety.services import arrangement_gaps
from apps.venues.bookings import approve_booking, request_booking
from apps.venues.models import BookingStatus, VenueBlock, VenueBlockHistory, VenueBooking
from apps.venues.tests.conftest import make_venue
from conftest import make_event

pytestmark = pytest.mark.django_db
START = datetime(2027, 6, 8, 10, tzinfo=ZoneInfo("Asia/Singapore"))


@pytest.fixture
def booked(organiser, coordinator, open_venue, venue_staff):
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        expected_attendance=30,
        preferred_start=START,
        preferred_end=START + timedelta(hours=2),
    )
    booking = request_booking(
        event=event,
        venue=open_venue,
        requested_by=coordinator,
        starts_at=START,
        ends_at=START + timedelta(hours=2),
        attendance=30,
    )
    approve_booking(booking, venue_staff)
    return booking


def block(api, staff, booking, **overrides):
    api.force_authenticate(staff)
    return api.post(
        f"/api/venues/{booking.venue_id}/blocks/",
        {
            "reason": "Exit damaged",
            "reason_category": "SAFETY_CONCERN",
            "starts_at": START.isoformat(),
            "ends_at": (START + timedelta(hours=1)).isoformat(),
            **overrides,
        },
        format="json",
    )


def test_disruption_preserves_original_and_returns_confirmed_event_to_planning(
    api, booked, venue_staff
):
    event = booked.event
    event.status = EventStatus.CONFIRMED  # Unit fixture; not a Safety/confirmation journey.
    event.save(update_fields=["status"])
    response = block(api, venue_staff, booked)
    assert response.status_code == 201
    booked.refresh_from_db()
    event.refresh_from_db()
    assert booked.status == BookingStatus.DISRUPTED
    assert event.status == EventStatus.PLANNING
    assert booked.starts_at == START and booked.decided_by_id == venue_staff.pk
    assert response.data["affected_bookings"][0]["id"] == booked.pk
    assert booked.history.filter(to_status=BookingStatus.DISRUPTED, actor=venue_staff).exists()
    assert set(
        Notification.objects.filter(kind=NotificationKind.RESOURCE_UNAVAILABLE).values_list(
            "recipient_id", flat=True
        )
    ) == {event.coordinator_id, event.created_by_id}
    assert any(f"disrupted booking #{booked.pk}" in gap for gap in arrangement_gaps(event))
    api.delete(f"/api/venues/{booked.venue_id}/blocks/{response.data['id']}/")
    booked.refresh_from_db()
    assert booked.status == BookingStatus.DISRUPTED


def test_linked_replacement_is_pending_until_staff_approval(api, booked, venue_staff, coordinator):
    assert block(api, venue_staff, booked).status_code == 201
    venue = make_venue(name="Replacement", opens_at=time(8), closes_at=time(22))
    api.force_authenticate(coordinator)
    data = {
        "session_id": booked.session_id,
        "venue": venue.pk,
        "starts_at": START.isoformat(),
        "ends_at": booked.ends_at.isoformat(),
        "attendance": 30,
    }
    url = f"/api/events/{booked.event_id}/venue-bookings/"
    assert api.post(url, data, format="json").status_code == 400
    response = api.post(url, {**data, "replaces_id": booked.pk}, format="json")
    assert response.status_code == 201, response.data
    replacement = VenueBooking.objects.get(pk=response.data["booking"]["id"])
    assert replacement.replaces_id == booked.pk and replacement.status == BookingStatus.PENDING
    assert any("disrupted booking" in gap for gap in arrangement_gaps(booked.event))
    approve_booking(replacement, venue_staff)
    assert not any("disrupted booking" in gap for gap in arrangement_gaps(booked.event))
    booked.refresh_from_db()
    assert booked.status == BookingStatus.DISRUPTED


@pytest.mark.parametrize(
    "category", ["MAINTENANCE", "EQUIPMENT_FAILURE", "RENOVATION", "SAFETY_CONCERN", "OTHER"]
)
def test_reason_categories_and_history(api, booked, venue_staff, category):
    response = block(api, venue_staff, booked, reason_category=category)
    assert response.status_code == 201
    assert VenueBlockHistory.objects.get().reason_category == category


def test_failed_notification_rolls_back_everything(api, booked, venue_staff):
    with patch("apps.venues.bookings.notify", side_effect=RuntimeError("notice failed")):
        with pytest.raises(RuntimeError):
            block(api, venue_staff, booked)
    booked.refresh_from_db()
    assert booked.status == BookingStatus.APPROVED
    assert not VenueBlock.objects.exists() and not VenueBlockHistory.objects.exists()
    assert not booked.history.filter(to_status=BookingStatus.DISRUPTED).exists()


def test_half_open_period_and_invalid_category(api, booked, venue_staff):
    assert block(api, venue_staff, booked, reason_category="INVALID").status_code == 400
    response = block(
        api,
        venue_staff,
        booked,
        starts_at=booked.ends_at.isoformat(),
        ends_at=(booked.ends_at + timedelta(hours=1)).isoformat(),
    )
    assert response.status_code == 201 and response.data["affected_bookings"] == []
    booked.refresh_from_db()
    assert booked.status == BookingStatus.APPROVED


def test_coordinator_cannot_block_or_see_other_events(
    api, booked, coordinator, venue_staff, second_coordinator
):
    assert block(api, coordinator, booked).status_code == 403
    response = block(api, venue_staff, booked)
    assert response.status_code == 201
    api.force_authenticate(second_coordinator)
    response = api.get(f"/api/venues/{booked.venue_id}/blocks/")
    assert response.status_code == 200 and response.data[0]["affected_bookings"] == []


@pytest.mark.parametrize("held", [False, True])
def test_block_affects_multiple_events_but_preserves_other_sessions(
    api, booked, venue_staff, organiser, coordinator, held
):
    other = make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=30
    )
    future = request_booking(
        event=other,
        venue=booked.venue,
        requested_by=coordinator,
        starts_at=START + timedelta(hours=3),
        ends_at=START + timedelta(hours=4),
        attendance=30,
    )
    approve_booking(
        future,
        venue_staff,
        hold_until=timezone.now() + timedelta(hours=1) if held else None,
    )
    second_room = make_venue(name="Unaffected", opens_at=time(8), closes_at=time(22))
    unaffected = request_booking(
        event=booked.event,
        venue=second_room,
        requested_by=coordinator,
        session_name="Workshop",
        session_kind="BREAKOUT",
        starts_at=START,
        ends_at=booked.ends_at,
        attendance=20,
    )
    approve_booking(unaffected, venue_staff)
    response = block(api, venue_staff, booked, ends_at=(START + timedelta(hours=5)).isoformat())
    assert response.status_code == 201
    assert {b["id"] for b in response.data["affected_bookings"]} == {booked.pk, future.pk}
    unaffected.refresh_from_db()
    future.refresh_from_db()
    assert unaffected.status == BookingStatus.APPROVED
    assert future.status == BookingStatus.DISRUPTED


def test_extending_block_disrupts_booking_and_history_failure_rolls_back(api, booked, venue_staff):
    response = block(
        api,
        venue_staff,
        booked,
        starts_at=(START - timedelta(hours=2)).isoformat(),
        ends_at=START.isoformat(),
    )
    assert response.status_code == 201
    detail = f"/api/venues/{booked.venue_id}/blocks/{response.data['id']}/"
    with patch(
        "apps.venues.availability_views.snapshot", side_effect=RuntimeError("history failed")
    ):
        with pytest.raises(RuntimeError):
            api.patch(detail, {"ends_at": booked.ends_at.isoformat()}, format="json")
    booked.refresh_from_db()
    assert booked.status == BookingStatus.APPROVED
    assert VenueBlock.objects.get().ends_at == START
    assert (
        api.patch(detail, {"ends_at": booked.ends_at.isoformat()}, format="json").status_code == 200
    )
    booked.refresh_from_db()
    assert booked.status == BookingStatus.DISRUPTED


@pytest.mark.django_db(transaction=True)
def test_staff_block_races_with_approval_without_leaving_occupied_unavailable_venue(
    booked, venue_staff
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from rest_framework.test import APIClient

    # Explicit pending fixture; the two competing HTTP actions create the outcome.
    VenueBooking.objects.filter(pk=booked.pk).update(status=BookingStatus.PENDING)
    gate = Barrier(2)

    def run(creating_block):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(venue_staff)
            gate.wait(timeout=10)
            if creating_block:
                return block(client, venue_staff, booked).status_code
            return client.post(
                f"/api/venue-bookings/{booked.pk}/approve/", {}, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [True, False]))
    assert results[0] == 201 and results[1] in (200, 409)
    booked.refresh_from_db()
    assert booked.status in (BookingStatus.PENDING, BookingStatus.DISRUPTED)


def test_replacement_service_refuses_non_disrupted_booking(booked, coordinator):
    from apps.venues.bookings import BookingValidationError, request_replacement

    with pytest.raises(BookingValidationError):
        request_replacement(disrupted_booking=booked, venue=booked.venue, requested_by=coordinator)
