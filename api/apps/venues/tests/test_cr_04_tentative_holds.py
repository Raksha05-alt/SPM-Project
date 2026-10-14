"""Week 7 change 4 - tentative venue holds expire.

CR4-AC1  Venue Staff may approve a request as a tentative hold, with an expiry
         date/time they choose (clarification: after approval, set by staff).
CR4-AC2  A hold reserves the venue until it expires; a pending request does not.
CR4-AC3  The expiry must be in the future and before the booking starts.
CR4-AC4  Venue Staff can change the expiry.
CR4-AC5  The coordinator completes the hold by confirming it, which makes it a booking.
CR4-AC6  An unconfirmed hold expires at its deadline and the venue becomes available.
CR4-AC7  The coordinator is warned before the hold expires and told when it does.
CR4-AC8  An expired hold is never treated as a confirmed booking.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.safety.tests.helpers import approve_safety
from apps.venues.bookings import process_holds
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.occupancy import clashes
from apps.venues.tests.helpers import book, iso
from conftest import make_event

HOUR = timezone.timedelta(hours=1)
DAY = timezone.timedelta(days=1)


@pytest.fixture
def held(pending):
    """A request Venue Staff approved as a hold that expires in three days."""
    pending.status = BookingStatus.HELD
    pending.hold_expires_at = timezone.now() + 3 * DAY
    pending.save()
    return pending


def approve(client, booking, hold_until=None):
    payload = {"hold_until": iso(hold_until)} if hold_until else {}
    return client.post(f"/api/venue-bookings/{booking.pk}/approve/", payload, format="json")


def expire_now(booking):
    VenueBooking.objects.filter(pk=booking.pk).update(
        hold_expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )


# --- CR4-AC1 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac1_staff_approve_a_request_as_a_hold_with_their_own_deadline(
    signed_in_venue_staff, venue_staff, pending, coordinator
):
    deadline = timezone.now() + 2 * DAY

    response = approve(signed_in_venue_staff, pending, deadline)

    assert response.status_code == 200, response.data
    assert response.data["status"] == BookingStatus.HELD
    assert response.data["hold_expires_at"] == iso(timezone.localtime(deadline))
    assert response.data["hold_set_by_name"] == venue_staff.get_full_name()
    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.BOOKING_DECIDED)
    assert "tentatively held" in note.message and "Confirm the hold" in note.message


@pytest.mark.django_db
def test_cr4_ac1_approving_without_a_deadline_is_still_a_confirmed_booking(
    signed_in_venue_staff, pending
):
    assert approve(signed_in_venue_staff, pending).data["status"] == BookingStatus.APPROVED


# --- CR4-AC2 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac2_a_hold_reserves_the_venue(
    signed_in_venue_staff, organiser, coordinator, held, venue
):
    other = make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, name="Other"
    )
    rival = book(other, venue, held.start, held.end, status=BookingStatus.PENDING)

    response = signed_in_venue_staff.post(f"/api/venue-bookings/{rival.pk}/approve/")

    assert response.status_code == 409
    assert response.data["conflicts"][0]["status"] == BookingStatus.HELD


@pytest.mark.django_db
def test_cr4_ac2_the_calendar_shows_the_hold_and_its_deadline(signed_in_venue_staff, held, venue):
    response = signed_in_venue_staff.get(
        f"/api/venues/{venue.pk}/availability/", {"start": iso(held.start), "end": iso(held.end)}
    )

    [segment] = response.data["segments"]
    assert segment["status"] == "TENTATIVE"
    assert segment["detail"].startswith("Tentative hold until")


@pytest.mark.django_db
def test_cr4_ac2_a_pending_request_does_not_reserve_the_venue(
    signed_in_venue_staff, organiser, coordinator, pending, venue
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    rival = book(other, venue, pending.start, pending.end, status=BookingStatus.PENDING)

    assert signed_in_venue_staff.post(f"/api/venue-bookings/{rival.pk}/approve/").status_code == 200


# --- CR4-AC3 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac3_a_hold_cannot_expire_in_the_past(signed_in_venue_staff, pending):
    response = approve(signed_in_venue_staff, pending, timezone.now() - HOUR)

    assert response.status_code == 400
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_cr4_ac3_a_hold_must_expire_before_the_booking_starts(signed_in_venue_staff, pending):
    response = approve(signed_in_venue_staff, pending, pending.start + HOUR)

    assert response.status_code == 400
    assert "before the booking starts" in response.data["detail"]


# --- CR4-AC4 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac4_staff_extend_a_hold_and_the_coordinator_is_told(
    signed_in_venue_staff, held, coordinator
):
    later = timezone.now() + 5 * DAY

    response = signed_in_venue_staff.post(
        f"/api/venue-bookings/{held.pk}/update-hold/", {"hold_until": iso(later)}, format="json"
    )

    assert response.status_code == 200, response.data
    held.refresh_from_db()
    assert held.hold_expires_at == later
    assert held.hold_warning_sent_at is None
    assert Notification.objects.filter(
        recipient=coordinator, message__contains="now expires"
    ).exists()


@pytest.mark.django_db
def test_cr4_ac4_only_venue_staff_change_a_hold(signed_in_coordinator, held):
    response = signed_in_coordinator.post(
        f"/api/venue-bookings/{held.pk}/update-hold/",
        {"hold_until": iso(timezone.now() + 5 * DAY)},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_cr4_ac4_an_expired_or_approved_hold_cannot_be_changed(
    signed_in_venue_staff, held, approved
):
    expire_now(held)
    for booking in (held, approved):
        response = signed_in_venue_staff.post(
            f"/api/venue-bookings/{booking.pk}/update-hold/",
            {"hold_until": iso(timezone.now() + DAY)},
            format="json",
        )
        assert response.status_code == 409


@pytest.mark.django_db
def test_cr4_ac4_a_deadline_is_required(signed_in_venue_staff, held):
    response = signed_in_venue_staff.post(
        f"/api/venue-bookings/{held.pk}/update-hold/", {}, format="json"
    )

    assert response.status_code == 400


# --- CR4-AC5 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac5_the_coordinator_confirms_the_hold(
    signed_in_coordinator, held, coordinator, venue_staff
):
    response = signed_in_coordinator.post(f"/api/venue-bookings/{held.pk}/confirm-hold/")

    assert response.status_code == 200, response.data
    held.refresh_from_db()
    assert held.status == BookingStatus.APPROVED
    assert held.hold_confirmed_by == coordinator
    assert Notification.objects.filter(
        recipient=venue_staff, message__contains="confirmed the hold"
    ).exists()


@pytest.mark.django_db
def test_cr4_ac5_only_the_assigned_coordinator_confirms(api, second_coordinator, venue_staff, held):
    for who in (second_coordinator, venue_staff):
        api.force_authenticate(who)
        assert api.post(f"/api/venue-bookings/{held.pk}/confirm-hold/").status_code == 403


@pytest.mark.django_db
def test_cr4_ac5_only_a_hold_can_be_confirmed(signed_in_coordinator, pending):
    assert (
        signed_in_coordinator.post(f"/api/venue-bookings/{pending.pk}/confirm-hold/").status_code
        == 409
    )


@pytest.mark.django_db
def test_cr4_ac5_an_expired_hold_cannot_be_confirmed(signed_in_coordinator, held):
    expire_now(held)

    response = signed_in_coordinator.post(f"/api/venue-bookings/{held.pk}/confirm-hold/")

    assert response.status_code == 409
    held.refresh_from_db()
    assert held.status == BookingStatus.EXPIRED


# --- CR4-AC6 / AC7 -------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac6_an_overdue_hold_expires_and_frees_the_venue(
    signed_in_venue_staff, organiser, coordinator, held, venue
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    rival = book(other, venue, held.start, held.end, status=BookingStatus.PENDING)
    expire_now(held)

    response = signed_in_venue_staff.post(f"/api/venue-bookings/{rival.pk}/approve/")

    assert response.status_code == 200
    held.refresh_from_db()
    assert held.status == BookingStatus.EXPIRED
    assert held.expired_at is not None


@pytest.mark.django_db
def test_cr4_ac7_the_coordinator_is_told_when_a_hold_expires(held, coordinator):
    expire_now(held)

    assert process_holds() == {"expired": 1, "warned": 0}
    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.HOLD_EXPIRED)
    assert "no longer reserved" in note.message


@pytest.mark.django_db
def test_cr4_ac7_the_coordinator_is_warned_once_before_expiry(held, coordinator, settings):
    settings.HOLD_WARNING_HOURS = 24
    VenueBooking.objects.filter(pk=held.pk).update(hold_expires_at=timezone.now() + 3 * HOUR)

    first = process_holds()
    second = process_holds()

    assert (first, second) == ({"expired": 0, "warned": 1}, {"expired": 0, "warned": 0})
    note = Notification.objects.get(recipient=coordinator, kind=NotificationKind.HOLD_EXPIRING)
    assert "Confirm it before then" in note.message


@pytest.mark.django_db
def test_cr4_ac7_no_warning_while_the_deadline_is_far_away(held, settings):
    settings.HOLD_WARNING_HOURS = 24

    assert process_holds() == {"expired": 0, "warned": 0}


@pytest.mark.django_db
def test_cr4_ac7_the_scheduled_command_processes_holds(held):
    expire_now(held)
    out = StringIO()

    call_command("process_venue_holds", stdout=out)

    assert "Expired 1 hold(s)" in out.getvalue()


# --- CR4-AC8 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr4_ac8_an_expired_hold_stops_occupying_even_before_it_is_processed(held, venue):
    expire_now(held)

    assert not clashes(venue, held.start, held.end, event_id=None).exists()
    held.refresh_from_db()
    assert held.status == BookingStatus.HELD  # not yet processed, yet not counted


@pytest.mark.django_db
def test_cr4_ac8_a_hold_is_not_a_booking_for_confirmation(signed_in_coordinator, event, held):
    approve_safety(event)

    response = signed_in_coordinator.post(f"/api/events/{event.pk}/confirm/")

    assert response.status_code == 409
    assert any("only tentatively held" in m["detail"] for m in response.data["missing"])


@pytest.mark.django_db
def test_cr4_ac8_an_expired_hold_is_not_a_booking_for_confirmation(
    signed_in_coordinator, event, held
):
    expire_now(held)
    approve_safety(event)

    response = signed_in_coordinator.post(f"/api/events/{event.pk}/confirm/")

    assert response.status_code == 409
    assert response.data["missing"][0]["detail"] == "No venue booking has been approved."


@pytest.mark.django_db
def test_cr4_ac8_a_confirmed_hold_lets_the_event_be_confirmed(signed_in_coordinator, event, held):
    signed_in_coordinator.post(f"/api/venue-bookings/{held.pk}/confirm-hold/")
    approve_safety(event)

    assert signed_in_coordinator.post(f"/api/events/{event.pk}/confirm/").status_code == 200


@pytest.mark.django_db
def test_cr4_ac8_a_hold_can_be_withdrawn(signed_in_coordinator, held):
    response = signed_in_coordinator.post(f"/api/venue-bookings/{held.pk}/withdraw/")

    assert response.data["status"] == BookingStatus.WITHDRAWN
