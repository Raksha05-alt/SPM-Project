"""SCRUM-11 (US-12.1) - request a venue booking."""

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.tests.helpers import block, booking_payload, iso, make_user
from conftest import make_event, make_venue

URL = "/api/venue-bookings/"


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)


@pytest.mark.django_db
def test_ac1_the_booking_records_the_event_date_and_timing(signed_in_coordinator, event, venue):
    start = event.preferred_start + timezone.timedelta(hours=1)
    end = start + timezone.timedelta(hours=2)

    response = signed_in_coordinator.post(
        URL, booking_payload(event, venue, start=iso(start), end=iso(end)), format="json"
    )

    assert response.status_code == 201, response.data
    booking = VenueBooking.objects.get()
    assert (booking.start, booking.end) == (start, end)
    assert booking.event == event


@pytest.mark.django_db
def test_ac2_the_booking_records_capacity_layout_accessibility_and_facilities(
    signed_in_coordinator, event, venue
):
    payload = booking_payload(
        event,
        venue,
        attendance=140,
        layout="CLASSROOM",
        facilities=["Projector", " Video conferencing ", "projector"],
        accessibility_needs="Two wheelchair users",
    )

    response = signed_in_coordinator.post(URL, payload, format="json")

    assert response.status_code == 201, response.data
    booking = VenueBooking.objects.get()
    assert booking.attendance == 140
    assert booking.layout == "CLASSROOM"
    assert booking.facilities == ["Projector", "Video conferencing"]
    assert booking.accessibility_needs == "Two wheelchair users"
    assert response.data["layout_label"] == "Classroom"


@pytest.mark.django_db
def test_ac3_missing_required_information_is_identified(signed_in_coordinator):
    response = signed_in_coordinator.post(URL, {}, format="json")

    assert response.status_code == 400
    assert set(response.data) >= {"event", "venue", "start", "end", "attendance"}
    assert response.data["start"] == ["Enter the date and start time."]
    assert response.data["attendance"] == ["Enter the expected attendance."]
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"attendance": 0}, "attendance"),
        ({"layout": "BALLROOM"}, "layout"),
        ({"facilities": "Projector"}, "facilities"),
        ({"facilities": [1, 2]}, "facilities"),
        ({"venue": 999999}, "venue"),
        ({"event": 999999}, "event"),
    ],
)
def test_ac3_invalid_values_are_identified(signed_in_coordinator, event, venue, change, field):
    response = signed_in_coordinator.post(
        URL, booking_payload(event, venue, **change), format="json"
    )

    assert response.status_code == 400
    assert field in response.data
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_ac3_an_end_before_the_start_is_refused(signed_in_coordinator, event, venue):
    payload = booking_payload(
        event, venue, start=iso(event.preferred_end), end=iso(event.preferred_start)
    )

    response = signed_in_coordinator.post(URL, payload, format="json")

    assert response.status_code == 400
    assert response.data["end"] == ["The end must be after the start."]


@pytest.mark.django_db
def test_ac3_a_period_in_the_past_is_refused(signed_in_coordinator, event, venue):
    start = timezone.now() - timezone.timedelta(days=1)
    payload = booking_payload(
        event, venue, start=iso(start), end=iso(start + timezone.timedelta(hours=2))
    )

    response = signed_in_coordinator.post(URL, payload, format="json")

    assert response.status_code == 400
    assert "start" in response.data


@pytest.mark.django_db
def test_ac3_an_unsuitable_venue_is_refused_with_the_reasons(signed_in_coordinator, event):
    small = make_venue(name="Small Room", capacity=50)

    response = signed_in_coordinator.post(URL, booking_payload(event, small), format="json")

    assert response.status_code == 400
    assert response.data["unmet"] == [
        "Expected attendance of 100 exceeds the venue's capacity of 50."
    ]
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_ac3_a_venue_blocked_for_the_period_is_refused(signed_in_coordinator, event, venue):
    block(venue, event.preferred_start, event.preferred_end, reason="Roof repairs")

    response = signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 409
    assert "Roof repairs" in response.data["detail"]
    assert response.data["blocks"][0]["reason"] == "Roof repairs"


@pytest.mark.django_db
def test_ac4_a_complete_request_goes_to_venue_staff_and_is_confirmed(
    signed_in_coordinator, coordinator, venue_staff, event, venue
):
    other_staff = make_user("venue2@connectsphere.example", Role.VENUE_STAFF)
    make_user("gone@connectsphere.example", Role.VENUE_STAFF, is_active=False)

    response = signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 201
    assert response.data["status"] == BookingStatus.PENDING
    assert response.data["status_display"] == "Pending review"
    assert response.data["requested_by_name"] == "Cora Coordinator"
    notified = Notification.objects.filter(kind=NotificationKind.BOOKING_REQUESTED)
    assert {n.recipient for n in notified} == {venue_staff, other_staff}
    assert "Harbour Hall" in notified.first().message


@pytest.mark.django_db
def test_ac4_the_first_request_moves_an_approved_event_into_planning(
    signed_in_coordinator, coordinator, organiser, event, venue
):
    signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert EventStatusHistory.objects.filter(
        event=event, from_status=EventStatus.APPROVED, to_status=EventStatus.PLANNING
    ).exists()
    assert Notification.objects.filter(
        recipient=organiser, kind=NotificationKind.STATUS_CHANGED
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_ac4_later_requests_leave_the_event_status_alone(
    signed_in_coordinator, organiser, coordinator, venue, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 201
    event.refresh_from_db()
    assert event.status == status


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
        EventStatus.REJECTED,
    ],
)
def test_ac4_events_not_yet_approved_or_closed_cannot_have_venues_requested(
    signed_in_coordinator, organiser, coordinator, venue, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 409
    assert "once the event is approved" in response.data["detail"]


@pytest.mark.django_db
def test_ac5_the_request_status_is_shown_when_viewing_the_event(
    signed_in_coordinator, event, venue
):
    signed_in_coordinator.post(URL, booking_payload(event, venue), format="json")

    listed = signed_in_coordinator.get(URL, {"event": event.pk})

    assert listed.status_code == 200
    [row] = listed.data
    assert (row["venue_name"], row["status_display"]) == ("Harbour Hall", "Pending review")


@pytest.mark.django_db
def test_ac6_a_coordinator_not_assigned_to_the_event_is_refused(api, organiser, venue):
    assigned = make_user("other@connectsphere.example", Role.EVENT_COORDINATOR)
    event = make_event(organiser, status=EventStatus.APPROVED, coordinator=assigned)
    outsider = make_user("outsider@connectsphere.example", Role.EVENT_COORDINATOR)
    api.force_authenticate(outsider)

    response = api.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 403
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_ac6_venue_staff_cannot_request_a_venue(signed_in_venue_staff, event, venue):
    response = signed_in_venue_staff.post(URL, booking_payload(event, venue), format="json")

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["signed_in_organiser"])
def test_ac6_clients_cannot_reach_venue_bookings(request, fixture, event, venue):
    client = request.getfixturevalue(fixture)

    assert client.post(URL, booking_payload(event, venue), format="json").status_code == 403
    assert client.get(URL).status_code == 403


@pytest.mark.django_db
def test_drafts_cannot_have_venues_requested(signed_in_coordinator, organiser, coordinator, venue):
    draft = make_event(organiser, coordinator=coordinator)

    response = signed_in_coordinator.post(URL, booking_payload(draft, venue), format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_listing_filters_validate_their_values(signed_in_coordinator):
    assert signed_in_coordinator.get(URL, {"status": "LOST"}).status_code == 400
    assert signed_in_coordinator.get(URL, {"event": "x"}).status_code == 400
    assert signed_in_coordinator.get(URL, {"venue": "x"}).status_code == 400


@pytest.mark.django_db
def test_ac6_the_service_itself_refuses_a_coordinator_who_is_not_assigned(event, venue):
    from apps.venues.bookings import NotAllowed, request_booking

    outsider = make_user("svc@connectsphere.example", Role.EVENT_COORDINATOR)

    with pytest.raises(NotAllowed):
        request_booking(event, outsider, {"venue": venue})
