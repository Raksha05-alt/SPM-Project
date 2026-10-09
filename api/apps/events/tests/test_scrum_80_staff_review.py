"""SCRUM-80 (US-19.3) - apply an approved change through staff review."""

import pytest

from apps.equipment.tests.conftest import hold
from apps.events.models import ChangeRequest
from apps.events.tests.change_helpers import DAY, confirmed_event
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book
from conftest import make_event


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


@pytest.fixture
def moved(api, coordinator, setup):
    """An approved change that moves the event one day later."""
    event = setup[0]
    change = ChangeRequest.objects.create(
        event=event,
        description="One day later",
        proposed_start=event.preferred_start + DAY,
        proposed_end=event.preferred_end + DAY,
    )
    api.force_authenticate(coordinator)
    api.post(f"/api/change-requests/{change.pk}/approve/", {"reason": "Agreed"}, format="json")
    for obj in setup[1:3]:
        obj.refresh_from_db()
    event.refresh_from_db()
    return setup


def review_booking(client, booking, **data):
    return client.post(f"/api/venue-bookings/{booking.pk}/review/", data, format="json")


def review_equipment(client, item, **data):
    return client.post(f"/api/equipment-requests/{item.pk}/review/", data, format="json")


@pytest.mark.django_db
def test_ac1_each_affected_arrangement_is_listed_for_review(moved):
    _, booking, item, _ = moved

    assert booking.review_required and item.review_required
    assert booking.review_start is not None


@pytest.mark.django_db
def test_ac1_an_approved_change_to_a_planning_event_also_goes_to_review(
    api, organiser, coordinator
):
    from apps.core.statuses import EventStatus
    from conftest import make_venue

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    booking = book(event, make_venue())
    change = ChangeRequest.objects.create(
        event=event, description="More people", proposed_attendance=130
    )
    api.force_authenticate(coordinator)

    api.post(f"/api/change-requests/{change.pk}/approve/", {"reason": "OK"}, format="json")

    booking.refresh_from_db()
    assert booking.review_required is True


@pytest.mark.django_db
def test_ac2_venue_staff_record_the_revised_booking_with_who_and_when(api, venue_staff, moved):
    event, booking, _, _ = moved
    api.force_authenticate(venue_staff)

    response = review_booking(api, booking, accommodated=True, note="Same room")

    assert response.status_code == 200, response.data
    booking.refresh_from_db()
    assert (booking.start, booking.end) == (event.preferred_start, event.preferred_end)
    assert booking.review_required is False
    assert (booking.reviewed_by, booking.status) == (venue_staff, BookingStatus.APPROVED)
    assert booking.reviewed_at is not None
    assert response.data["reviewed_by_name"] == "Vera Venue"


@pytest.mark.django_db
def test_ac2_a_revised_period_that_is_taken_is_refused(
    api, venue_staff, organiser, coordinator, moved
):
    from apps.core.statuses import EventStatus

    event, booking, _, _ = moved
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    book(rival, booking.venue, event.preferred_start, event.preferred_end)
    api.force_authenticate(venue_staff)

    response = review_booking(api, booking, accommodated=True)

    assert response.status_code == 409
    assert response.data["conflicts"]


@pytest.mark.django_db
def test_ac2_staff_can_give_their_own_revised_times(api, venue_staff, moved):
    _, booking, _, _ = moved
    start = booking.review_start + DAY
    api.force_authenticate(venue_staff)

    bad = review_booking(
        api, booking, accommodated=True, start=start.isoformat(), end=start.isoformat()
    )
    good = review_booking(
        api,
        booking,
        accommodated=True,
        start=start.isoformat(),
        end=(start + (booking.end - booking.start)).isoformat(),
    )

    assert bad.status_code == 400
    assert good.status_code == 200


@pytest.mark.django_db
def test_ac2_technical_staff_move_the_reservation(api, tech_staff, moved):
    event, _, item, _ = moved
    api.force_authenticate(tech_staff)

    response = review_equipment(api, item, accommodated=True)

    assert response.status_code == 200, response.data
    reservation = item.active_reservations().get()
    assert (reservation.start, reservation.end) == (event.preferred_start, event.preferred_end)
    assert response.data["reviewed_by_name"] == "Tariq Tech"
    assert response.data["review_required"] is False


@pytest.mark.django_db
def test_ac2_equipment_short_in_the_new_period_cannot_be_moved(
    api, tech_staff, organiser, coordinator, moved
):
    from apps.core.statuses import EventStatus

    event, _, item, _ = moved
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    hold(rival, item.equipment_type, 4, event.preferred_start, event.preferred_end)
    api.force_authenticate(tech_staff)

    response = review_equipment(api, item, accommodated=True)

    assert response.status_code == 409
    assert response.data["available_quantity"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["venue", "equipment"])
def test_ac3_when_staff_cannot_accommodate_the_original_stays(
    api, venue_staff, tech_staff, organiser, moved, kind
):
    _, booking, item, _ = moved
    original = (booking.start, booking.end)
    if kind == "venue":
        api.force_authenticate(venue_staff)
        response = review_booking(api, booking, accommodated=False, note="Fully booked")
    else:
        api.force_authenticate(tech_staff)
        response = review_equipment(api, item, accommodated=False, note="Fully booked")

    assert response.status_code == 200
    assert response.data["review_outcome"] == "Could not accommodate the change: Fully booked"
    booking.refresh_from_db()
    assert (booking.start, booking.end) == original
    note = Notification.objects.get(recipient=organiser, kind=NotificationKind.REVIEW_OUTCOME)
    assert "stays in place" in note.message


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["venue", "equipment"])
def test_ac3_a_reason_is_needed_when_not_accommodated(api, venue_staff, tech_staff, moved, kind):
    _, booking, item, _ = moved
    if kind == "venue":
        api.force_authenticate(venue_staff)
        response = review_booking(api, booking, accommodated=False)
    else:
        api.force_authenticate(tech_staff)
        response = review_equipment(api, item, accommodated=False)

    assert response.status_code == 400


@pytest.mark.django_db
def test_ac4_a_revised_arrangement_notifies_client_and_registered_attendees(
    api, venue_staff, organiser, moved
):
    _, booking, _, attendee = moved
    Notification.objects.all().delete()
    api.force_authenticate(venue_staff)

    review_booking(api, booking, accommodated=True)

    assert Notification.objects.filter(
        recipient=organiser, kind=NotificationKind.REVIEW_OUTCOME
    ).exists()
    note = Notification.objects.get(recipient=attendee)
    assert "have changed" in note.message and "Harbour Hall" in note.message


@pytest.mark.django_db
def test_ac5_the_history_shows_the_request_decision_outcomes_and_staff(
    api, venue_staff, tech_staff, coordinator, moved
):
    event, booking, item, _ = moved
    api.force_authenticate(venue_staff)
    review_booking(api, booking, accommodated=True)
    api.force_authenticate(tech_staff)
    review_equipment(api, item, accommodated=False, note="Lamps away")
    api.force_authenticate(coordinator)

    history = api.get(f"/api/events/{event.pk}/history/").data

    rows = {(r["field"], r["changed_by_name"]) for r in history}
    assert ("Change request", "Cora Coordinator") in rows
    assert ("Venue booking: Harbour Hall", "Vera Venue") in rows
    assert ("Equipment: Projector", "Tariq Tech") in rows
    assert ("preferred_start", "Cora Coordinator") in rows
    decision = next(r for r in history if r["field"] == "Change request")
    assert decision["new_value"] == "Approved: Agreed"


@pytest.mark.django_db
def test_arrangements_not_flagged_cannot_be_reviewed(api, venue_staff, tech_staff, setup):
    _, booking, item, _ = setup
    api.force_authenticate(venue_staff)
    assert review_booking(api, booking, accommodated=True).status_code == 409
    api.force_authenticate(tech_staff)
    assert review_equipment(api, item, accommodated=True).status_code == 409


@pytest.mark.django_db
def test_only_the_matching_staff_review(signed_in_coordinator, moved):
    _, booking, item, _ = moved

    assert review_booking(signed_in_coordinator, booking, accommodated=True).status_code == 403
    assert review_equipment(signed_in_coordinator, item, accommodated=True).status_code == 403


@pytest.mark.django_db
def test_the_outcome_must_be_stated(api, venue_staff, moved):
    api.force_authenticate(venue_staff)

    response = review_booking(api, moved[1])

    assert response.data["accommodated"] == ["Say whether the change can be accommodated."]


@pytest.mark.django_db
def test_equipment_with_nothing_reserved_is_simply_cleared(api, tech_staff, moved):
    from apps.equipment.models import EquipmentType
    from apps.equipment.tests.conftest import make_request

    event = moved[0]
    item = make_request(
        event,
        EquipmentType.objects.create(name="Mic", total_quantity=1),
        1,
        review_required=True,
        review_reason="Changed",
    )
    api.force_authenticate(tech_staff)

    assert review_equipment(api, item, accommodated=True).status_code == 200
