"""Week 7 change 1 - venue setup and turnaround time.

CR1-AC1  Each venue has a configurable setup time and turnaround time.
CR1-AC2  A booking occupies the venue from (start - setup) to (end + turnaround):
         10:00-12:00 with 30 and 45 minutes occupies 09:30-12:45.
CR1-AC3  Conflict detection uses the occupied periods; approval is refused.
CR1-AC4  Availability (calendar, search, shortlist) uses the occupied periods.
CR1-AC5  Bookings that become problematic when the buffers change are identified,
         never removed.
CR1-AC6  Buffers apply to venues only, not to equipment (clarification).
CR1-AC7  Venue Staff decide about buffers outside opening hours: warned, not refused.
"""

from datetime import time

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentType
from apps.equipment.services import available_quantity
from apps.equipment.tests.conftest import hold
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.occupancy import clashes
from apps.venues.tests.helpers import block, book, booking_payload, iso
from conftest import future_at, make_event, make_venue

MIN = timezone.timedelta(minutes=1)


@pytest.fixture
def hall(db):
    return make_venue(name="Buffered Hall", setup_minutes=30, turnaround_minutes=45)


@pytest.fixture
def morning(organiser, coordinator):
    """The briefing's example: an event from 10:00 to 12:00."""
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Morning Briefing",
        preferred_start=future_at(10, 10),
        preferred_end=future_at(10, 12),
    )


@pytest.fixture
def rival(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator, name="Rival")


@pytest.fixture
def morning_booking(morning, hall):
    return book(morning, hall, future_at(10, 10), future_at(10, 12))


# --- CR1-AC1 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr1_ac1_venue_staff_set_setup_and_turnaround(signed_in_venue_staff, hall):
    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/",
        {"setup_minutes": 20, "turnaround_minutes": 60},
        format="json",
    )

    assert response.status_code == 200, response.data
    hall.refresh_from_db()
    assert (hall.setup_minutes, hall.turnaround_minutes) == (20, 60)
    assert response.data["setup_minutes"] == 20


@pytest.mark.django_db
@pytest.mark.parametrize("value", [-5, 24 * 60 + 1])
def test_cr1_ac1_buffers_must_be_sensible(signed_in_venue_staff, hall, value):
    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"setup_minutes": value}, format="json"
    )

    assert response.status_code == 400
    assert "setup_minutes" in response.data


@pytest.mark.django_db
def test_cr1_ac1_new_venues_default_to_no_buffer(db):
    venue = make_venue(name="Plain Room")

    assert (venue.setup_minutes, venue.turnaround_minutes) == (0, 0)


# --- CR1-AC2 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr1_ac2_the_briefing_example_occupies_0930_to_1245(signed_in_venue_staff, morning_booking):
    data = signed_in_venue_staff.get(f"/api/venue-bookings/{morning_booking.pk}/").data

    assert data["occupied_from"] == iso(future_at(10, 9, 30))
    assert data["occupied_until"] == iso(future_at(10, 12, 45))
    assert (data["setup_minutes"], data["turnaround_minutes"]) == (30, 45)


# --- CR1-AC3 -----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end", "clash"),
    [
        # The rival's setup (30) would start before the morning's turnaround (45) ends.
        ((10, 13, 14), (10, 15), True),
        # Exactly turnaround + setup after: 12:00 + 45 + 30 = 13:15. Half-open, no clash.
        ((10, 13, 15), (10, 15), False),
        # Before: the rival's turnaround must end by the morning's setup at 09:30.
        ((10, 7, 0), (10, 8, 46), True),
        ((10, 7, 0), (10, 8, 45), False),
    ],
)
def test_cr1_ac3_conflicts_include_setup_and_turnaround(
    hall, morning_booking, rival, start, end, clash
):
    found = clashes(hall, future_at(*start), future_at(*end), event_id=rival.pk)

    assert found.exists() is clash


@pytest.mark.django_db
def test_cr1_ac3_a_request_inside_the_turnaround_is_flagged_and_cannot_be_approved(
    signed_in_coordinator, api, venue_staff, hall, morning_booking, rival
):
    response = signed_in_coordinator.post(
        "/api/venue-bookings/",
        booking_payload(rival, hall, start=iso(future_at(10, 12, 30)), end=iso(future_at(10, 14))),
        format="json",
    )

    assert response.status_code == 201, response.data
    [conflict] = response.data["conflicts"]
    assert conflict["event_name"] == "Morning Briefing"
    assert conflict["occupied_until"] == future_at(10, 12, 45)

    api.force_authenticate(venue_staff)
    refused = api.post(f"/api/venue-bookings/{response.data['id']}/approve/")
    assert refused.status_code == 409
    assert "setup and turnaround" in refused.data["detail"]
    assert VenueBooking.objects.get(pk=response.data["id"]).status == BookingStatus.PENDING


@pytest.mark.django_db
def test_cr1_ac3_a_block_during_setup_prevents_the_request(signed_in_coordinator, hall, morning):
    block(hall, future_at(10, 9), future_at(10, 9, 45), reason="Floor polishing")

    response = signed_in_coordinator.post(
        "/api/venue-bookings/", booking_payload(morning, hall), format="json"
    )

    assert response.status_code == 409
    assert "including setup and turnaround" in response.data["detail"]


@pytest.mark.django_db
def test_cr1_ac3_a_block_after_the_turnaround_does_not(signed_in_coordinator, hall, morning):
    block(hall, future_at(10, 12, 45), future_at(10, 14), reason="Cleaning")

    response = signed_in_coordinator.post(
        "/api/venue-bookings/", booking_payload(morning, hall), format="json"
    )

    assert response.status_code == 201


# --- CR1-AC4 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr1_ac4_the_calendar_shows_setup_and_turnaround(
    signed_in_venue_staff, hall, morning_booking
):
    response = signed_in_venue_staff.get(
        f"/api/venues/{hall.pk}/availability/",
        {"start": iso(future_at(10, 9)), "end": iso(future_at(10, 13))},
    )

    rows = [(s["status"], s["detail"], s["start"], s["end"]) for s in response.data["segments"]]
    assert rows == [
        ("AVAILABLE", "", future_at(10, 9), future_at(10, 9, 30)),
        ("CONFIRMED", "Setup", future_at(10, 9, 30), future_at(10, 10)),
        ("CONFIRMED", "Confirmed booking", future_at(10, 10), future_at(10, 12)),
        ("CONFIRMED", "Turnaround", future_at(10, 12), future_at(10, 12, 45)),
        ("AVAILABLE", "", future_at(10, 12, 45), future_at(10, 13)),
    ]


@pytest.mark.django_db
def test_cr1_ac4_search_leaves_out_a_venue_whose_buffers_clash(
    signed_in_coordinator, hall, morning_booking
):
    def found(start, end):
        response = signed_in_coordinator.get(
            "/api/venues/search/", {"start": iso(future_at(*start)), "end": iso(future_at(*end))}
        )
        return hall.name in [row["name"] for row in response.data["results"]]

    assert not found((10, 13), (10, 14))  # inside turnaround + setup
    assert found((10, 13, 15), (10, 14))


@pytest.mark.django_db
def test_cr1_ac4_the_shortlist_reports_a_buffer_clash(
    signed_in_coordinator, coordinator, organiser, hall, morning_booking
):
    later = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=future_at(10, 13),
        preferred_end=future_at(10, 14),
    )
    signed_in_coordinator.post(
        f"/api/events/{later.pk}/shortlist/", {"venue": hall.pk}, format="json"
    )

    [row] = signed_in_coordinator.get(f"/api/events/{later.pk}/shortlist/").data

    assert row["no_longer_available"] is True


# --- CR1-AC5 -----------------------------------------------------------------


@pytest.fixture
def tight(hall, morning_booking, rival):
    """Two bookings exactly far enough apart under 30 + 45 minutes."""
    return book(rival, hall, future_at(10, 13, 15), future_at(10, 15))


@pytest.mark.django_db
def test_cr1_ac5_longer_buffers_identify_bookings_that_now_clash(
    signed_in_venue_staff, hall, morning_booking, tight, venue_staff, coordinator
):
    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"turnaround_minutes": 60}, format="json"
    )

    assert response.status_code == 200
    assert {row["id"] for row in response.data["flagged_bookings"]} == {
        morning_booking.pk,
        tight.pk,
    }
    for booking in (morning_booking, tight):
        booking.refresh_from_db()
        assert booking.status == BookingStatus.APPROVED  # identified, not removed
        assert booking.review_required is True
        assert "turnaround of 60 min" in booking.review_reason
    assert Notification.objects.filter(
        recipient=venue_staff, kind=NotificationKind.REVIEW_NEEDED
    ).exists()
    assert Notification.objects.filter(
        recipient=coordinator, kind=NotificationKind.REVIEW_NEEDED
    ).exists()


@pytest.mark.django_db
def test_cr1_ac5_unchanged_or_harmless_buffers_flag_nothing(
    signed_in_venue_staff, hall, morning_booking, tight
):
    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"setup_minutes": 30, "name": "Buffered Hall"}, format="json"
    )
    shorter = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"turnaround_minutes": 15}, format="json"
    )

    assert response.data["flagged_bookings"] == []
    assert shorter.data["flagged_bookings"] == []
    tight.refresh_from_db()
    assert tight.review_required is False


@pytest.mark.django_db
def test_cr1_ac5_past_bookings_are_not_flagged(signed_in_venue_staff, hall, morning, rival):
    past = timezone.now() - timezone.timedelta(days=2)
    book(morning, hall, past, past + timezone.timedelta(hours=1))
    book(rival, hall, past + timezone.timedelta(hours=2), past + timezone.timedelta(hours=3))

    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"turnaround_minutes": 240}, format="json"
    )

    assert response.data["flagged_bookings"] == []


# --- CR1-AC6 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr1_ac6_equipment_is_not_padded(morning, rival):
    projector = EquipmentType.objects.create(name="Projector", total_quantity=1)
    hold(morning, projector, 1, future_at(10, 10), future_at(10, 12))

    # Straight after the morning event the projector is free again.
    assert available_quantity(projector, future_at(10, 12), future_at(10, 13)) == 1


# --- CR1-AC7 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr1_ac7_buffers_outside_opening_hours_are_a_warning_not_a_refusal(
    signed_in_coordinator, organiser, coordinator
):
    room = make_venue(
        name="Nine To Five",
        opens_at=time(9, 0),
        closes_at=time(17, 0),
        setup_minutes=60,
        turnaround_minutes=0,
    )
    early = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=future_at(10, 9),
        preferred_end=future_at(10, 11),
    )

    response = signed_in_coordinator.post(
        "/api/venue-bookings/", booking_payload(early, room), format="json"
    )

    assert response.status_code == 201, response.data
    [warning] = response.data["buffer_warnings"]
    assert "from 08:00 to 11:00" in warning


@pytest.mark.django_db
def test_cr1_ac7_no_warning_when_buffers_fit(signed_in_venue_staff, morning_booking):
    data = signed_in_venue_staff.get(f"/api/venue-bookings/{morning_booking.pk}/").data

    assert data["buffer_warnings"] == []
