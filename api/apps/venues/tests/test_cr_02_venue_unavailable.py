"""Week 7 change 2 - a venue becomes unavailable after it was booked.

CR2-AC1  Venue Staff mark a venue temporarily unavailable with a reason category
         (maintenance, equipment failure, renovation, safety, other), even when
         future events are already booked there.
CR2-AC2  The affected bookings are identified; the events are not cancelled.
CR2-AC3  The relevant coordinators are told alternative arrangements are needed;
         the client is told too.
CR2-AC4  The original event and booking information is preserved.
CR2-AC5  The coordinator searches for and requests a replacement venue.
CR2-AC6  A confirmed event with a venue issue returns to planning (clarification).
CR2-AC7  The event cannot be confirmed while a disrupted booking is unresolved.
"""

import pytest

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.tests.conftest import enrol, make_attendee
from apps.venues.models import BlockCategory, BookingStatus, VenueBooking
from apps.venues.tests.helpers import book, iso
from conftest import future_at, make_event, make_venue


@pytest.fixture
def hall(db):
    return make_venue(name="Harbour Hall", turnaround_minutes=30)


@pytest.fixture
def planned(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Partner Summit",
        preferred_start=future_at(20, 10),
        preferred_end=future_at(20, 16),
    )


@pytest.fixture
def booking(planned, hall):
    return book(planned, hall, session_name="Main programme")


def block_venue(client, venue, start, end, category="MAINTENANCE", reason="Air-con repair"):
    return client.post(
        f"/api/venues/{venue.pk}/blocks/",
        {"start": iso(start), "end": iso(end), "category": category, "reason": reason},
        format="json",
    )


# --- CR2-AC1 / AC2 -----------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("category", [c.value for c in BlockCategory])
def test_cr2_ac1_staff_block_a_booked_venue_for_any_operational_reason(
    signed_in_venue_staff, hall, booking, category
):
    response = block_venue(
        signed_in_venue_staff, hall, future_at(20, 8), future_at(20, 18), category=category
    )

    assert response.status_code == 201, response.data
    assert response.data["category"] == category
    assert [row["id"] for row in response.data["affected_bookings"]] == [booking.pk]


@pytest.mark.django_db
def test_cr2_ac2_the_booking_is_marked_unavailable_and_the_event_is_kept(
    signed_in_venue_staff, hall, booking, planned
):
    block_venue(signed_in_venue_staff, hall, future_at(20, 12), future_at(20, 13))

    booking.refresh_from_db()
    planned.refresh_from_db()
    assert booking.status == BookingStatus.DISRUPTED
    assert "Air-con repair" in booking.disruption_reason
    assert "maintenance" in booking.disruption_reason
    assert booking.disrupted_at is not None
    assert planned.status == EventStatus.PLANNING


@pytest.mark.django_db
def test_cr2_ac2_a_block_in_the_turnaround_also_affects_the_booking(
    signed_in_venue_staff, hall, booking
):
    # The booking ends 16:00 and the venue needs 30 minutes to reset.
    response = block_venue(signed_in_venue_staff, hall, future_at(20, 16, 15), future_at(20, 18))

    assert len(response.data["affected_bookings"]) == 1


@pytest.mark.django_db
def test_cr2_ac2_bookings_outside_the_block_are_untouched(signed_in_venue_staff, hall, booking):
    response = block_venue(signed_in_venue_staff, hall, future_at(21, 8), future_at(21, 18))

    assert response.data["affected_bookings"] == []
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


@pytest.mark.django_db
def test_cr2_ac2_pending_requests_and_holds_are_affected_too(
    signed_in_venue_staff, hall, organiser, coordinator
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    pending = book(other, hall, future_at(20, 9), future_at(20, 10), status=BookingStatus.PENDING)

    block_venue(signed_in_venue_staff, hall, future_at(20, 8), future_at(20, 18))

    pending.refresh_from_db()
    assert pending.status == BookingStatus.DISRUPTED


@pytest.mark.django_db
def test_cr2_ac2_taking_a_venue_out_of_service_affects_every_future_booking(
    signed_in_venue_staff, hall, booking, organiser, coordinator
):
    later = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    second = book(later, hall, future_at(40, 9), future_at(40, 10))

    response = signed_in_venue_staff.patch(
        f"/api/venues/{hall.pk}/", {"is_active": False}, format="json"
    )

    assert response.status_code == 200
    assert {row["id"] for row in response.data["disrupted_bookings"]} == {booking.pk, second.pk}
    assert set(VenueBooking.objects.values_list("status", flat=True)) == {BookingStatus.DISRUPTED}


@pytest.mark.django_db
def test_cr2_ac2_an_edited_block_that_now_covers_a_booking_affects_it(
    signed_in_venue_staff, hall, booking
):
    created = block_venue(signed_in_venue_staff, hall, future_at(21, 8), future_at(21, 9))

    signed_in_venue_staff.patch(
        f"/api/venue-blocks/{created.data['id']}/",
        {"start": iso(future_at(20, 8)), "end": iso(future_at(21, 9))},
        format="json",
    )

    booking.refresh_from_db()
    assert booking.status == BookingStatus.DISRUPTED


@pytest.mark.django_db
def test_cr2_ac2_cancelled_and_past_events_are_left_alone(
    signed_in_venue_staff, hall, organiser, coordinator
):
    from django.utils import timezone

    cancelled = make_event(organiser, status=EventStatus.CANCELLED, coordinator=coordinator)
    released = book(cancelled, hall, future_at(20, 9), future_at(20, 10))
    past = timezone.now() - timezone.timedelta(days=1)
    done = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    old = book(done, hall, past - timezone.timedelta(hours=2), past)

    signed_in_venue_staff.patch(f"/api/venues/{hall.pk}/", {"is_active": False}, format="json")

    released.refresh_from_db()
    old.refresh_from_db()
    assert released.status == old.status == BookingStatus.APPROVED


# --- CR2-AC3 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr2_ac3_the_coordinator_and_client_are_told_alternatives_are_needed(
    signed_in_venue_staff, hall, booking, coordinator, organiser
):
    block_venue(signed_in_venue_staff, hall, future_at(20, 8), future_at(20, 18))

    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.VENUE_UNAVAILABLE)
    assert "Alternative arrangements are required" in note.message
    assert "Harbour Hall (Main programme)" in note.message
    client = Notification.objects.get(recipient=organiser, kind=NotificationKind.VENUE_UNAVAILABLE)
    assert "not cancelled" in client.message


@pytest.mark.django_db
def test_cr2_ac3_an_unassigned_event_alerts_the_leads(signed_in_venue_staff, hall, organiser, lead):
    waiting = make_event(organiser, status=EventStatus.APPROVED)
    book(waiting, hall, future_at(20, 9), future_at(20, 10))

    block_venue(signed_in_venue_staff, hall, future_at(20, 8), future_at(20, 18))

    assert Notification.objects.filter(
        recipient=lead, kind=NotificationKind.VENUE_UNAVAILABLE
    ).exists()


# --- CR2-AC4 / AC5 -------------------------------------------------------------


@pytest.mark.django_db
def test_cr2_ac4_and_ac5_a_replacement_keeps_the_original_on_record(
    api, venue_staff, coordinator, hall, booking, planned
):
    api.force_authenticate(venue_staff)
    block_venue(api, hall, future_at(20, 8), future_at(20, 18))
    elsewhere = make_venue(name="Riverside Room", capacity=200)
    api.force_authenticate(coordinator)

    # The coordinator can still search for a venue for the original period.
    search = api.get(
        "/api/venues/search/",
        {"start": iso(planned.preferred_start), "end": iso(planned.preferred_end)},
    )
    assert [row["name"] for row in search.data["results"]] == ["Riverside Room"]

    response = api.post(
        f"/api/venue-bookings/{booking.pk}/replace/", {"venue": elsewhere.pk}, format="json"
    )

    assert response.status_code == 201, response.data
    assert response.data["venue_name"] == "Riverside Room"
    assert response.data["session_name"] == "Main programme"
    assert response.data["status"] == BookingStatus.PENDING
    booking.refresh_from_db()
    assert booking.status == BookingStatus.DISRUPTED
    assert booking.replaced_by_id == response.data["id"]
    planned.refresh_from_db()
    assert (planned.name, planned.preferred_start) == ("Partner Summit", future_at(20, 10))


@pytest.mark.django_db
def test_cr2_ac5_only_a_disrupted_booking_is_replaced_once(
    signed_in_coordinator, api, venue_staff, coordinator, hall, booking
):
    elsewhere = make_venue(name="Riverside Room")
    assert (
        signed_in_coordinator.post(
            f"/api/venue-bookings/{booking.pk}/replace/", {"venue": elsewhere.pk}, format="json"
        ).status_code
        == 409
    )
    api.force_authenticate(venue_staff)
    block_venue(api, hall, future_at(20, 8), future_at(20, 18))
    api.force_authenticate(coordinator)
    api.post(f"/api/venue-bookings/{booking.pk}/replace/", {"venue": elsewhere.pk}, format="json")

    again = api.post(
        f"/api/venue-bookings/{booking.pk}/replace/", {"venue": elsewhere.pk}, format="json"
    )

    assert again.status_code == 409


@pytest.mark.django_db
def test_cr2_ac5_only_the_assigned_coordinator_replaces(
    api, venue_staff, second_coordinator, hall, booking
):
    api.force_authenticate(venue_staff)
    block_venue(api, hall, future_at(20, 8), future_at(20, 18))
    api.force_authenticate(second_coordinator)

    response = api.post(
        f"/api/venue-bookings/{booking.pk}/replace/",
        {"venue": make_venue(name="X").pk},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_cr2_ac5_a_disrupted_booking_can_be_dropped_instead(
    api, venue_staff, coordinator, hall, booking
):
    api.force_authenticate(venue_staff)
    block_venue(api, hall, future_at(20, 8), future_at(20, 18))
    api.force_authenticate(coordinator)

    response = api.post(f"/api/venue-bookings/{booking.pk}/withdraw/")

    assert response.status_code == 200
    assert response.data["status"] == BookingStatus.WITHDRAWN
    assert response.data["disruption_reason"]


# --- CR2-AC6 / AC7 -------------------------------------------------------------


@pytest.mark.django_db
def test_cr2_ac6_a_confirmed_event_returns_to_planning_and_attendees_hear(
    signed_in_venue_staff, hall, organiser, coordinator
):
    confirmed = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala"
    )
    book(confirmed, hall, future_at(20, 18), future_at(20, 22))
    attendee = make_attendee("guest@example.com")
    enrol(confirmed, attendee)

    block_venue(
        signed_in_venue_staff,
        hall,
        future_at(20, 17),
        future_at(20, 23),
        "SAFETY",
        "Fire alarm fault",
    )

    confirmed.refresh_from_db()
    assert confirmed.status == EventStatus.PLANNING
    assert confirmed.status_history.filter(
        from_status=EventStatus.CONFIRMED, to_status=EventStatus.PLANNING
    ).exists()
    assert Notification.objects.filter(
        recipient=attendee, kind=NotificationKind.EVENT_CHANGED
    ).exists()


@pytest.mark.django_db
def test_cr2_ac7_an_unresolved_disruption_blocks_confirmation(
    api, venue_staff, coordinator, hall, booking, planned
):
    from apps.safety.tests.helpers import approve_safety

    other_room = make_venue(name="Annex")
    book(planned, other_room)
    api.force_authenticate(venue_staff)
    block_venue(api, hall, future_at(20, 8), future_at(20, 18))
    approve_safety(planned)
    api.force_authenticate(coordinator)

    response = api.post(f"/api/events/{planned.pk}/confirm/")

    assert response.status_code == 409
    assert any("became unavailable" in m["detail"] for m in response.data["missing"])
