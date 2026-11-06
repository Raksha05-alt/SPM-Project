"""SCRUM-11 - Request a venue booking (Sprint 3 gate G09).

As an Event Coordinator, I want to request a venue for an event, so that I can
secure the space and have the request reviewed by Venue Staff.

The booking record and its rules were published at gate G02
(test_scrum_11_booking_contract.py); this file proves the request journey.
Case IDs follow the Sprint 3 guide: S3-SCRUM-11-<case>.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.venues.bookings import create_booking_record, transition_booking
from apps.venues.models import BookingStatus, VenueBlock, VenueBooking
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime.datetime(2027, 3, 1, 10, 0, tzinfo=SGT)
END = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=SGT)


def bookings_url(event):
    return f"/api/events/{event.pk}/venue-bookings/"


INBOX = "/api/venue-bookings/"


@pytest.fixture
def hall(db):
    """Fits the guide's example exactly: capacity 60, Theatre, open 08:00-22:00 daily."""
    return make_venue(
        name="Harbour Hall",
        capacity=60,
        layouts=["THEATRE", "BANQUET"],
        facilities=["Video conferencing", "Hearing loop"],
        wheelchair_access=True,
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )


@pytest.fixture
def event(organiser, coordinator):
    return make_event(
        organiser, status=EventStatus.APPROVED, coordinator=coordinator, expected_attendance=60
    )


def payload(for_venue, **overrides):
    data = {
        "venue": for_venue.pk if for_venue is not None else None,
        "starts_at": START.isoformat(),
        "ends_at": END.isoformat(),
        "attendance": 60,
        "layout": "THEATRE",
        "required_facilities": ["Video conferencing"],
        "wheelchair_access_required": True,
        "accessibility_notes": "Two wheelchair users.",
    }
    data.update(overrides)
    return data


def request_as(api, user, for_event, for_venue, **overrides):
    # Overrides may replace the venue itself, for example with None or an unknown id.
    api.force_authenticate(user)
    return api.post(bookings_url(for_event), payload(for_venue, **overrides), format="json")


# S3-SCRUM-11-01 - AC1/AC2: date, timing and requirements are saved exactly. ----


@pytest.mark.django_db
def test_s3_11_01_ac1_ac2_the_request_is_saved_with_its_timing_and_requirements(
    api, coordinator, event, hall
):
    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 201
    booking = VenueBooking.objects.get()
    # 10:00-12:00 Singapore is 02:00-04:00 UTC: compare instants, not formatting.
    assert booking.starts_at == datetime.datetime(2027, 3, 1, 2, 0, tzinfo=datetime.UTC)
    assert booking.ends_at == datetime.datetime(2027, 3, 1, 4, 0, tzinfo=datetime.UTC)
    assert (booking.event, booking.venue, booking.attendance, booking.layout) == (
        event,
        hall,
        60,
        "THEATRE",
    )
    assert booking.required_facilities == ["Video conferencing"]
    assert booking.wheelchair_access_required is True
    assert booking.accessibility_notes == "Two wheelchair users."
    assert booking.status == BookingStatus.PENDING
    assert booking.requested_by == coordinator
    fresh = api.get(bookings_url(event)).data[0]
    assert fresh["venue_name"] == "Harbour Hall"
    assert fresh["layout_name"] == "Theatre"
    assert fresh["status"] == BookingStatus.PENDING


@pytest.mark.django_db
def test_s3_11_01_the_first_request_starts_planning_an_approved_event(
    api, coordinator, event, hall
):
    request_as(api, coordinator, event, hall)

    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert EventStatusHistory.objects.filter(
        event=event,
        from_status=EventStatus.APPROVED,
        to_status=EventStatus.PLANNING,
        changed_by=coordinator,
    ).exists()


@pytest.mark.django_db
def test_s3_11_01_a_planning_event_can_request_more_venues(api, organiser, coordinator, hall):
    event = make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=60
    )
    garden = make_venue(
        name="Garden Room",
        capacity=80,
        layouts=["THEATRE"],
        facilities=["Video conferencing"],
        wheelchair_access=True,
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )

    first = request_as(api, coordinator, event, hall)
    second = request_as(api, coordinator, event, garden)

    assert (first.status_code, second.status_code) == (201, 201)
    assert VenueBooking.objects.filter(event=event, status=BookingStatus.PENDING).count() == 2
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING


@pytest.mark.django_db
def test_s3_11_01_the_requester_comes_from_the_session_not_the_payload(
    api, coordinator, second_coordinator, event, hall
):
    request_as(api, coordinator, event, hall, requested_by=second_coordinator.pk, status="APPROVED")

    booking = VenueBooking.objects.get()
    assert booking.requested_by == coordinator
    assert booking.status == BookingStatus.PENDING


# S3-SCRUM-11-02 - AC3: missing or invalid information is refused, item by item.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"venue": None}, "venue"),
        ({"starts_at": None}, "starts_at"),
        ({"ends_at": None}, "ends_at"),
        ({"ends_at": START.isoformat()}, "ends_at"),
        ({"attendance": None}, "attendance"),
        ({"attendance": 0}, "attendance"),
        ({"layout": "CABARET"}, "layout"),
        ({"venue": 99999}, "venue"),
    ],
)
def test_s3_11_02_ac3_missing_or_invalid_information_is_refused_with_nothing_saved(
    api, coordinator, event, hall, overrides, field
):
    response = request_as(api, coordinator, event, hall, **overrides)

    assert response.status_code == 400
    assert field in response.data
    assert not VenueBooking.objects.exists()
    event.refresh_from_db()
    assert event.status == EventStatus.APPROVED


@pytest.mark.django_db
def test_s3_11_02_ac3_every_missing_item_is_identified_at_once(api, coordinator, event, hall):
    response = request_as(
        api, coordinator, event, hall, starts_at=None, ends_at=None, attendance=None
    )

    assert response.status_code == 400
    assert {"starts_at", "ends_at", "attendance"} <= set(response.data)


# S3-SCRUM-11-03 - AC4: sent to Venue Staff, with confirmation. ---------------


@pytest.mark.django_db
def test_s3_11_03_ac4_the_request_reaches_venue_staff_and_the_coordinator_is_told(
    api, coordinator, venue_staff, event, hall
):
    response = request_as(api, coordinator, event, hall)

    assert response.data["detail"] == "Your request for Harbour Hall has been sent to Venue Staff."
    notice = Notification.objects.get(kind=NotificationKind.VENUE_REQUESTED)
    assert notice.recipient == venue_staff
    assert "Harbour Hall" in notice.message
    assert "01 Mar 2027 10:00" in notice.message  # Singapore time, as people read it

    api.force_authenticate(venue_staff)
    inbox = api.get(INBOX, {"status": "PENDING"})
    assert inbox.status_code == 200
    assert [(row["event_name"], row["venue_name"], row["status"]) for row in inbox.data] == [
        (event.name, "Harbour Hall", BookingStatus.PENDING)
    ]
    assert inbox.data[0]["organisation_name"] == "Acme Pte Ltd"
    assert inbox.data[0]["requested_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["coordinator", "lead", "organiser", "attendee"])
def test_s3_11_03_only_venue_staff_open_the_booking_request_inbox(api, request, role):
    api.force_authenticate(request.getfixturevalue(role))

    assert api.get(INBOX).status_code == 403


@pytest.mark.django_db
def test_s3_11_03_the_inbox_refuses_an_unknown_status_filter(api, venue_staff):
    api.force_authenticate(venue_staff)

    assert api.get(INBOX, {"status": "MAYBE"}).status_code == 400


# S3-SCRUM-11-04 - AC5: the event shows each request's current status. -------


@pytest.mark.django_db
def test_s3_11_04_ac5_the_event_shows_the_current_status_of_its_requests(
    api, coordinator, venue_staff, event, hall
):
    request_as(api, coordinator, event, hall)
    booking = VenueBooking.objects.get()
    assert api.get(bookings_url(event)).data[0]["status_label"] == "Pending"

    transition_booking(booking, BookingStatus.APPROVED, venue_staff)

    row = api.get(bookings_url(event)).data[0]
    assert row["status"] == BookingStatus.APPROVED
    assert row["status_label"] == "Approved"
    assert row["decided_by_name"] == "Vera Venue"


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["lead", "venue_staff"])
def test_s3_11_04_leads_and_venue_staff_can_read_an_events_requests(
    api, request, coordinator, event, hall, role
):
    request_as(api, coordinator, event, hall)
    api.force_authenticate(request.getfixturevalue(role))

    response = api.get(bookings_url(event))

    assert response.status_code == 200
    assert len(response.data) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["second_coordinator", "organiser", "attendee"])
def test_s3_11_04_others_cannot_read_an_events_requests(
    api, request, coordinator, event, hall, role
):
    request_as(api, coordinator, event, hall)
    user = request.getfixturevalue(role)
    api.force_authenticate(user)

    assert api.get(bookings_url(event)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


# S3-SCRUM-11-05 - AC6: only the assigned coordinator requests a venue. -------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role", ["second_coordinator", "lead", "venue_staff", "organiser", "attendee"]
)
def test_s3_11_05_ac6_anyone_but_the_assigned_coordinator_is_refused(
    api, request, event, hall, role
):
    user = request.getfixturevalue(role)

    response = request_as(api, user, event, hall)

    assert response.status_code == 403
    assert not VenueBooking.objects.exists()
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()
    event.refresh_from_db()
    assert event.status == EventStatus.APPROVED


@pytest.mark.django_db
def test_s3_11_05_ac6_a_previous_coordinator_is_refused_after_reassignment(
    api, coordinator, second_coordinator, event, hall
):
    event.coordinator = second_coordinator
    event.save(update_fields=["coordinator"])

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 403
    assert not VenueBooking.objects.exists()


# S3-SCRUM-11-06 - SCRUM-71 AC4: an unsuitable venue is refused, no booking. ---


@pytest.mark.django_db
@pytest.mark.parametrize("attendance, created", [(59, True), (60, True), (61, False)])
def test_s3_11_06_capacity_equal_to_attendance_remains_eligible(
    api, coordinator, event, hall, attendance, created
):
    # SCRUM-87: the main programme follows the event's attendance.
    event.expected_attendance = attendance
    event.save(update_fields=["expected_attendance"])
    response = request_as(api, coordinator, event, hall, attendance=attendance)

    assert response.status_code == (201 if created else 400)
    assert VenueBooking.objects.exists() is created
    if not created:
        assert [r["requirement"] for r in response.data["unmet_requirements"]] == ["CAPACITY"]


@pytest.mark.django_db
def test_s3_11_06_every_unmet_requirement_is_stated_and_nothing_is_saved(
    api, coordinator, event, hall
):
    event.expected_attendance = 70
    event.save(update_fields=["expected_attendance"])
    response = request_as(
        api,
        coordinator,
        event,
        hall,
        attendance=70,
        layout="BOARDROOM",
        required_facilities=["Video conferencing", "Stage"],
        starts_at=datetime.datetime(2027, 3, 1, 21, 0, tzinfo=SGT).isoformat(),
        ends_at=datetime.datetime(2027, 3, 1, 23, 0, tzinfo=SGT).isoformat(),
    )

    assert response.status_code == 400
    requirements = {r["requirement"] for r in response.data["unmet_requirements"]}
    assert requirements == {"CAPACITY", "LAYOUT", "FACILITY", "OPERATING_HOURS"}
    assert not VenueBooking.objects.exists()
    assert not Notification.objects.filter(kind=NotificationKind.VENUE_REQUESTED).exists()
    event.refresh_from_db()
    assert event.status == EventStatus.APPROVED


@pytest.mark.django_db
def test_s3_11_06_wheelchair_access_not_recorded_is_not_assumed(api, coordinator, event, hall):
    hall.wheelchair_access = None
    hall.save(update_fields=["wheelchair_access"])

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 400
    assert [r["requirement"] for r in response.data["unmet_requirements"]] == ["ACCESSIBILITY"]


# S3-SCRUM-11-07 - a blocked, out-of-service or already approved venue. -------


@pytest.mark.django_db
def test_s3_11_07_a_blocked_venue_cannot_be_requested(api, coordinator, event, hall):
    VenueBlock.objects.create(
        venue=hall,
        reason="Carpet replacement",
        starts_at=datetime.datetime(2027, 3, 1, 11, 0, tzinfo=SGT),
        ends_at=datetime.datetime(2027, 3, 1, 15, 0, tzinfo=SGT),
    )

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 409
    assert "Carpet replacement" in response.data["reasons"][0]
    assert "01 Mar 2027 11:00" in response.data["reasons"][0]
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_s3_11_07_an_out_of_service_venue_cannot_be_requested(api, coordinator, event, hall):
    hall.in_service = False
    hall.save(update_fields=["in_service"])

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 409
    assert response.data["reasons"] == ["The venue is out of service."]
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "other_start, other_end, refused",
    [
        ((9, 0), (10, 1), True),  # overlaps by a minute
        ((11, 59), (13, 0), True),
        ((8, 0), (10, 0), False),  # ends exactly as ours starts: adjacent
        ((12, 0), (14, 0), False),  # starts exactly as ours ends: adjacent
    ],
)
def test_s3_11_07_an_overlapping_approved_booking_refuses_the_request(
    api, organiser, coordinator, venue_staff, event, hall, other_start, other_end, refused
):
    other_event = make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=60
    )
    other = create_booking_record(
        requested_by=coordinator,
        event=other_event,
        venue=hall,
        starts_at=datetime.datetime(2027, 3, 1, *other_start, tzinfo=SGT),
        ends_at=datetime.datetime(2027, 3, 1, *other_end, tzinfo=SGT),
        attendance=40,
    )
    transition_booking(other, BookingStatus.APPROVED, venue_staff)

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == (409 if refused else 201)
    if refused:
        assert str(other_event.pk) in response.data["reasons"][0]
    assert VenueBooking.objects.filter(event=event).exists() is not refused


@pytest.mark.django_db
def test_s3_11_07_another_pending_request_does_not_reserve_the_venue(
    api, organiser, coordinator, event, hall
):
    other_event = make_event(
        organiser, status=EventStatus.PLANNING, coordinator=coordinator, expected_attendance=60
    )
    create_booking_record(
        requested_by=coordinator,
        event=other_event,
        venue=hall,
        starts_at=START,
        ends_at=END,
        attendance=40,
    )

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 201


# S3-SCRUM-11-08 - only approved events can request a venue. -------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CONFIRMED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_s3_11_08_a_venue_is_requested_only_for_an_approved_or_planning_event(
    api, organiser, coordinator, hall, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = request_as(api, coordinator, event, hall)

    assert response.status_code == 400
    assert "event" in response.data
    assert not VenueBooking.objects.exists()
    event.refresh_from_db()
    assert event.status == status


@pytest.mark.django_db
def test_s3_11_08_a_draft_is_refused(api, organiser, coordinator, hall):
    draft = make_event(organiser, coordinator=coordinator)

    response = request_as(api, coordinator, draft, hall)

    assert response.status_code == 400
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_s3_11_04_a_drafts_venue_requests_are_not_visible(api, organiser, coordinator):
    draft = make_event(organiser, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.get(bookings_url(draft))

    assert response.status_code == 403
    assert AuditLog.objects.get(actor=coordinator, allowed=False).detail == (
        "drafts are not visible to ConnectSphere"
    )
