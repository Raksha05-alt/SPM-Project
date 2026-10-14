"""Week 7 change 3 - multiple venues for one event.

CR3-AC1  One event can have several venue bookings at the same time (for example a
         main auditorium and breakout rooms), each named for its session.
CR3-AC2  Each venue is checked independently for suitability.
CR3-AC3  ...and for availability and conflicts.
CR3-AC4  Each venue is approved independently; the event is confirmed only when
         every one of its venue bookings is approved (clarification).
CR3-AC5  Withdrawing or changing one venue leaves the others in place; on a
         confirmed event only that venue goes back through approval.
CR3-AC6  The client and attendees see every confirmed venue.
CR3-AC7  A change of attendance re-checks the main room, not the breakout rooms.
"""

import pytest

from apps.core.statuses import EventStatus
from apps.events.tests.change_helpers import approve_change
from apps.safety.tests.helpers import approve_safety
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.tests.helpers import book, booking_payload
from conftest import make_event, make_venue

URL = "/api/venue-bookings/"


@pytest.fixture
def conference(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Annual Conference",
        expected_attendance=200,
    )


@pytest.fixture
def auditorium(db):
    return make_venue(name="Auditorium", capacity=250)


@pytest.fixture
def breakouts(db):
    return [make_venue(name=f"Breakout {letter}", capacity=40) for letter in "ABC"]


def request(client, event, venue, **extra):
    return client.post(URL, booking_payload(event, venue, **extra), format="json")


@pytest.mark.django_db
def test_cr3_ac1_an_event_books_an_auditorium_and_three_breakout_rooms_at_once(
    signed_in_coordinator, conference, auditorium, breakouts
):
    main = request(
        signed_in_coordinator, conference, auditorium, attendance=200, session_name="Main programme"
    )
    rooms = [
        request(
            signed_in_coordinator, conference, room, attendance=40, session_name=f"Breakout {i}"
        )
        for i, room in enumerate(breakouts, start=1)
    ]

    assert main.status_code == 201, main.data
    assert all(r.status_code == 201 for r in rooms), [r.data for r in rooms]
    assert VenueBooking.objects.filter(event=conference).count() == 4
    listed = signed_in_coordinator.get(URL, {"event": conference.pk}).data
    assert {row["session_name"] for row in listed} == {
        "Main programme",
        "Breakout 1",
        "Breakout 2",
        "Breakout 3",
    }
    assert all(row["conflicts"] == [] for row in listed)


@pytest.mark.django_db
def test_cr3_ac2_each_venue_is_checked_against_its_own_attendance(
    signed_in_coordinator, conference, breakouts
):
    fits = request(signed_in_coordinator, conference, breakouts[0], attendance=40)
    too_many = request(signed_in_coordinator, conference, breakouts[1], attendance=41)

    assert fits.status_code == 201
    assert too_many.status_code == 400
    assert "capacity of 40" in too_many.data["unmet"][0]


@pytest.mark.django_db
def test_cr3_ac3_a_conflict_at_one_venue_does_not_affect_the_others(
    signed_in_coordinator, organiser, coordinator, conference, auditorium, breakouts
):
    rival = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Expo"
    )
    book(rival, breakouts[0], conference.preferred_start, conference.preferred_end)

    main = request(signed_in_coordinator, conference, auditorium, attendance=200)
    clashing = request(signed_in_coordinator, conference, breakouts[0], attendance=30)

    assert main.data["conflicts"] == []
    assert [c["event_name"] for c in clashing.data["conflicts"]] == ["Expo"]


@pytest.mark.django_db
def test_cr3_ac4_each_venue_is_decided_independently(
    signed_in_venue_staff, conference, auditorium, breakouts
):
    main = book(conference, auditorium, status=BookingStatus.PENDING, attendance=200)
    room = book(conference, breakouts[0], status=BookingStatus.PENDING, attendance=30)

    approved = signed_in_venue_staff.post(f"{URL}{main.pk}/approve/")
    rejected = signed_in_venue_staff.post(
        f"{URL}{room.pk}/reject/", {"reason": "Painting"}, format="json"
    )

    assert approved.data["status"] == BookingStatus.APPROVED
    assert rejected.data["status"] == BookingStatus.REJECTED
    main.refresh_from_db()
    assert main.status == BookingStatus.APPROVED


@pytest.mark.django_db
def test_cr3_ac4_every_venue_must_be_approved_before_confirmation(
    signed_in_coordinator, conference, auditorium, breakouts
):
    book(conference, auditorium, attendance=200)
    book(
        conference,
        breakouts[0],
        status=BookingStatus.PENDING,
        attendance=30,
        session_name="Breakout 1",
    )
    approve_safety(conference)

    response = signed_in_coordinator.post(f"/api/events/{conference.pk}/confirm/")

    assert response.status_code == 409
    assert [m["detail"] for m in response.data["missing"]] == [
        "The request for Breakout A (Breakout 1) is awaiting a decision from Venue Staff."
    ]


@pytest.mark.django_db
def test_cr3_ac4_with_every_venue_approved_the_event_is_confirmed(
    signed_in_coordinator, conference, auditorium, breakouts
):
    book(conference, auditorium, attendance=200)
    book(conference, breakouts[0], attendance=30)
    approve_safety(conference)

    assert signed_in_coordinator.post(f"/api/events/{conference.pk}/confirm/").status_code == 200


@pytest.mark.django_db
def test_cr3_ac5_withdrawing_one_venue_leaves_the_others(
    signed_in_coordinator, conference, auditorium, breakouts
):
    main = book(conference, auditorium, attendance=200)
    room = book(conference, breakouts[0], attendance=30)

    response = signed_in_coordinator.post(
        f"{URL}{room.pk}/withdraw/", {"confirm": True}, format="json"
    )

    assert response.status_code == 200
    main.refresh_from_db()
    room.refresh_from_db()
    assert (main.status, room.status) == (BookingStatus.APPROVED, BookingStatus.WITHDRAWN)


@pytest.mark.django_db
def test_cr3_ac5_changing_one_venue_of_a_confirmed_event_reopens_only_that_venue(
    signed_in_coordinator, organiser, coordinator, auditorium, breakouts
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    main = book(event, auditorium, attendance=200)
    room = book(event, breakouts[0], attendance=30)
    approve_safety(event)

    signed_in_coordinator.post(f"{URL}{room.pk}/withdraw/", {"confirm": True}, format="json")
    replacement = request(signed_in_coordinator, event, breakouts[1], attendance=30)

    event.refresh_from_db()
    main.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert main.status == BookingStatus.APPROVED and not main.review_required
    assert replacement.data["status"] == BookingStatus.PENDING
    # The safety approval covered the old arrangement, so it is needed again.
    assert event.safety_checks.get().status == "SUPERSEDED"


@pytest.mark.django_db
def test_cr3_ac5_cancelling_the_event_releases_every_venue(
    signed_in_coordinator, conference, auditorium, breakouts
):
    bookings = [book(conference, auditorium, attendance=200)] + [
        book(conference, room, attendance=30) for room in breakouts
    ]

    signed_in_coordinator.post(f"/api/events/{conference.pk}/cancel/", {}, format="json")

    assert {VenueBooking.objects.get(pk=b.pk).status for b in bookings} == {BookingStatus.RELEASED}


@pytest.mark.django_db
def test_cr3_ac6_the_client_sees_every_confirmed_venue(
    api, coordinator, organiser, conference, auditorium, breakouts
):
    book(conference, auditorium, attendance=200, session_name="Main programme")
    book(conference, breakouts[0], attendance=30, session_name="Workshop")
    approve_safety(conference)
    api.force_authenticate(coordinator)
    api.post(f"/api/events/{conference.pk}/confirm/")
    api.force_authenticate(organiser)

    venues = api.get(f"/api/events/{conference.pk}/").data["confirmed_arrangements"]["venues"]

    assert [(v["venue"], v["session"]) for v in venues] == [
        ("Auditorium", "Main programme"),
        ("Breakout A", "Workshop"),
    ]


@pytest.mark.django_db
def test_cr3_ac7_more_attendees_recheck_the_main_room_not_the_breakouts(
    api, organiser, coordinator, auditorium, breakouts
):
    event = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, expected_attendance=200
    )
    main = book(event, auditorium, attendance=200)
    room = book(event, breakouts[0], attendance=30)

    approve_change(api, event, {"expected_attendance": 260})

    main.refresh_from_db()
    room.refresh_from_db()
    assert "exceeds the venue's capacity of 250" in main.review_reason
    assert "capacity" not in room.review_reason
