"""SCRUM-72 - Respond to a venue booking request (Sprint 3 gate G10).

As Venue Staff, I want to record my decision on a venue booking request, so
that the Event Coordinator knows whether the venue can be used.

Case IDs follow the Sprint 3 guide: S3-SCRUM-72-<case>.
"""

import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from apps.venues.bookings import (
    BookingValidationError,
    InvalidBookingTransition,
    VenueNotAvailable,
    approve_booking,
    create_booking_record,
)
from apps.venues.models import BookingStatus, VenueBlock, VenueBooking, VenueBookingHistory
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime.datetime(2027, 3, 1, 10, 0, tzinfo=SGT)
END = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=SGT)


def detail_url(booking):
    return f"/api/venue-bookings/{booking.pk}/"


def approve_url(booking):
    return f"/api/venue-bookings/{booking.pk}/approve/"


def reject_url(booking):
    return f"/api/venue-bookings/{booking.pk}/reject/"


@pytest.fixture
def hall(db):
    """Capacity 60, Theatre, open 08:00-22:00 daily: suits the 60-person request exactly."""
    return make_venue(
        name="Harbour Hall",
        capacity=60,
        layouts=["THEATRE"],
        facilities=["Video conferencing"],
        wheelchair_access=True,
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )


def pending(organiser, coordinator, venue, **overrides):
    event = overrides.pop("event", None) or make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Annual Gala",
        expected_attendance=60,
    )
    values = {
        "starts_at": START,
        "ends_at": END,
        "attendance": 60,
        "layout": "THEATRE",
        "required_facilities": ["Video conferencing"],
        "wheelchair_access_required": True,
        "accessibility_notes": "Two wheelchair users.",
    }
    values.update(overrides)
    return create_booking_record(requested_by=coordinator, event=event, venue=venue, **values)


@pytest.fixture
def booking(organiser, coordinator, hall):
    return pending(organiser, coordinator, hall)


@pytest.fixture
def staff_api(api, venue_staff):
    api.force_authenticate(venue_staff)
    return api


def decision_notices():
    return Notification.objects.filter(kind=NotificationKind.VENUE_DECIDED)


# S3-SCRUM-72-01 - AC1: opening a request shows the event, period and requirements.


@pytest.mark.django_db
def test_s3_72_01_ac1_staff_see_the_event_period_and_requirements(staff_api, booking):
    response = staff_api.get(detail_url(booking))

    assert response.status_code == 200
    data = response.data
    assert data["event"] == booking.event_id
    assert data["event_name"] == "Annual Gala"
    assert data["venue_name"] == "Harbour Hall"
    # 10:00-12:00 Singapore is 02:00-04:00 UTC: compare instants, not formatting.
    assert datetime.datetime.fromisoformat(data["starts_at"]) == START
    assert datetime.datetime.fromisoformat(data["ends_at"]) == END
    assert (data["attendance"], data["layout"], data["layout_name"]) == (60, "THEATRE", "Theatre")
    assert data["required_facilities"] == ["Video conferencing"]
    assert data["wheelchair_access_required"] is True
    assert data["accessibility_notes"] == "Two wheelchair users."
    assert data["status"] == BookingStatus.PENDING


@pytest.mark.django_db
def test_s3_72_01_ac1_the_pending_inbox_lists_the_request(staff_api, booking):
    rows = staff_api.get("/api/venue-bookings/?status=PENDING").data

    assert [row["id"] for row in rows] == [booking.pk]


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "organiser", "attendee", "lead"])
def test_s3_72_01_only_venue_staff_open_a_request(api, booking, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.get(detail_url(booking)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


# S3-SCRUM-72-02 - AC2/AC6: approval confirms the period, records who and when, notifies.


@pytest.mark.django_db
def test_s3_72_02_ac2_ac6_approval_is_recorded_and_the_coordinator_notified(
    staff_api, booking, venue_staff, coordinator, hall
):
    response = staff_api.post(approve_url(booking), {}, format="json")

    assert response.status_code == 200
    assert response.data["booking"]["status"] == BookingStatus.APPROVED
    assert response.data["booking"]["decided_by_name"] == "Vera Venue"
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert booking.decided_by == venue_staff
    assert booking.decided_at is not None
    # AC2 - the venue period is confirmed: an approved booking now occupies the venue.
    assert list(VenueBooking.objects.occupying().filter(venue=hall)) == [booking]
    last = booking.history.order_by("-pk").first()
    assert (last.from_status, last.to_status, last.actor) == (
        BookingStatus.PENDING,
        BookingStatus.APPROVED,
        venue_staff,
    )
    assert last.changed_at == booking.decided_at
    notice = decision_notices().get()
    assert notice.recipient == coordinator
    assert notice.event == booking.event
    assert "approved Harbour Hall" in notice.message
    assert "Annual Gala" in notice.message


@pytest.mark.django_db
def test_s3_72_02_ac6_the_payload_cannot_forge_the_decider_or_time(
    staff_api, booking, venue_staff, coordinator
):
    forged = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    staff_api.post(
        approve_url(booking),
        {"decided_by": coordinator.pk, "decided_at": forged.isoformat(), "status": "REJECTED"},
        format="json",
    )

    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert booking.decided_by == venue_staff
    assert booking.decided_at > forged


# S3-SCRUM-72-03 - AC3/AC4: rejection needs a reason, keeps it and notifies with it.


@pytest.mark.django_db
def test_s3_72_03_ac3_rejection_stores_the_reason_and_notifies_with_it(
    staff_api, booking, venue_staff, coordinator
):
    response = staff_api.post(
        reject_url(booking), {"reason": "  Hall closed for a private function.  "}, format="json"
    )

    assert response.status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.REJECTED
    assert booking.decision_reason == "Hall closed for a private function."
    assert (booking.decided_by, booking.decided_at is not None) == (venue_staff, True)
    last = booking.history.order_by("-pk").first()
    assert (last.to_status, last.reason, last.actor) == (
        BookingStatus.REJECTED,
        "Hall closed for a private function.",
        venue_staff,
    )
    notice = decision_notices().get()
    assert notice.recipient == coordinator
    assert "rejected Harbour Hall" in notice.message
    assert "Reason: Hall closed for a private function." in notice.message
    # A rejected request reserves nothing.
    assert not VenueBooking.objects.occupying().exists()


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   \n "}])
def test_s3_72_03_ac4_rejection_without_a_reason_is_blocked(staff_api, booking, body):
    response = staff_api.post(reject_url(booking), body, format="json")

    assert response.status_code == 400
    assert "reason" in response.data
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert (booking.decided_by, booking.decided_at, booking.decision_reason) == (None, None, "")
    assert booking.history.count() == 1
    assert not decision_notices().exists()


# S3-SCRUM-72-04 - AC5: a decided request cannot be decided again.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "first,second",
    [
        ("approve", "approve"),
        ("approve", "reject"),
        ("reject", "approve"),
        ("reject", "reject"),
    ],
)
def test_s3_72_04_ac5_a_second_decision_is_refused_without_overwriting(
    api, booking, venue_staff, first, second
):
    other_staff = type(venue_staff).objects.create_user(
        username="v2@connectsphere.example",
        email="v2@connectsphere.example",
        password="pw-for-tests-only",
        role=venue_staff.role,
    )
    urls = {"approve": approve_url, "reject": reject_url}
    api.force_authenticate(venue_staff)
    assert (
        api.post(urls[first](booking), {"reason": "First reason."}, format="json").status_code
        == 200
    )
    booking.refresh_from_db()
    before = (booking.status, booking.decided_by, booking.decided_at, booking.decision_reason)

    api.force_authenticate(other_staff)
    response = api.post(urls[second](booking), {"reason": "Second reason."}, format="json")

    assert response.status_code == 409
    booking.refresh_from_db()
    assert (
        booking.status,
        booking.decided_by,
        booking.decided_at,
        booking.decision_reason,
    ) == before
    assert booking.history.count() == 2
    assert decision_notices().count() == 1


@pytest.mark.django_db
def test_s3_72_04_ac5_a_withdrawn_request_cannot_be_decided(booking, venue_staff, coordinator):
    from apps.venues.bookings import transition_booking

    transition_booking(booking, BookingStatus.WITHDRAWN, coordinator)

    with pytest.raises(InvalidBookingTransition):
        approve_booking(booking, venue_staff)
    booking.refresh_from_db()
    assert booking.status == BookingStatus.WITHDRAWN


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "organiser", "attendee", "lead"])
def test_s3_72_04_only_venue_staff_decide(api, booking, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.post(approve_url(booking), {}, format="json").status_code == 403
    assert api.post(reject_url(booking), {"reason": "No."}, format="json").status_code == 403
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s3_72_04_an_unknown_request_is_not_found(staff_api):
    assert (
        staff_api.post("/api/venue-bookings/999999/approve/", {}, format="json").status_code == 404
    )


# S3-SCRUM-72-05 - approval rechecks the venue under locks; no partial decisions.


def assert_still_pending(booking):
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.decided_at is None
    assert booking.history.count() == 1
    assert not decision_notices().exists()


@pytest.mark.django_db
def test_s3_72_05_a_block_added_after_the_request_refuses_approval(staff_api, booking, hall):
    VenueBlock.objects.create(
        venue=hall,
        reason="Carpet replacement",
        starts_at=datetime.datetime(2027, 3, 1, 11, 0, tzinfo=SGT),
        ends_at=datetime.datetime(2027, 3, 1, 15, 0, tzinfo=SGT),
    )

    response = staff_api.post(approve_url(booking), {}, format="json")

    assert response.status_code == 409
    assert any("Carpet replacement" in reason for reason in response.data["reasons"])
    assert_still_pending(booking)


@pytest.mark.django_db
def test_s3_72_05_a_capacity_cut_after_the_request_refuses_approval(staff_api, booking, hall):
    hall.capacity = 59
    hall.save(update_fields=["capacity"])

    response = staff_api.post(approve_url(booking), {}, format="json")

    assert response.status_code == 409
    assert response.data["unmet_requirements"]
    assert_still_pending(booking)


@pytest.mark.django_db
def test_s3_72_05_capacity_equal_to_attendance_is_still_approved(staff_api, booking):
    # The hall's capacity is exactly 60, the requested attendance.
    assert staff_api.post(approve_url(booking), {}, format="json").status_code == 200


@pytest.mark.django_db
def test_s3_72_05_an_out_of_service_venue_refuses_approval(staff_api, booking, hall):
    hall.in_service = False
    hall.save(update_fields=["in_service"])

    response = staff_api.post(approve_url(booking), {}, format="json")

    assert response.status_code == 409
    assert "The venue is out of service." in response.data["reasons"]
    assert_still_pending(booking)


@pytest.mark.django_db
def test_s3_72_05_an_overlapping_approval_refuses_the_second(
    staff_api, organiser, coordinator, hall
):
    first = pending(organiser, coordinator, hall)
    second = pending(
        organiser,
        coordinator,
        hall,
        starts_at=END - datetime.timedelta(minutes=1),
        ends_at=END + datetime.timedelta(hours=1),
    )
    assert staff_api.post(approve_url(first), {}, format="json").status_code == 200

    response = staff_api.post(approve_url(second), {}, format="json")

    assert response.status_code == 409
    assert any(str(first.event_id) in reason for reason in response.data["reasons"])
    second.refresh_from_db()
    assert second.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_s3_72_05_an_adjacent_approval_is_allowed(staff_api, organiser, coordinator, hall):
    first = pending(organiser, coordinator, hall)
    second = pending(
        organiser, coordinator, hall, starts_at=END, ends_at=END + datetime.timedelta(hours=1)
    )
    assert staff_api.post(approve_url(first), {}, format="json").status_code == 200

    assert staff_api.post(approve_url(second), {}, format="json").status_code == 200


@pytest.mark.django_db
def test_s3_72_05_an_event_keeps_one_approved_venue(staff_api, organiser, coordinator, hall):
    garden = make_venue(
        name="Garden Room",
        capacity=80,
        layouts=["THEATRE"],
        facilities=["Video conferencing"],
        wheelchair_access=True,
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )
    first = pending(organiser, coordinator, hall)
    second = pending(organiser, coordinator, garden, event=first.event)
    assert staff_api.post(approve_url(first), {}, format="json").status_code == 200

    response = staff_api.post(approve_url(second), {}, format="json")

    assert response.status_code == 409
    assert "event" in response.data
    second.refresh_from_db()
    assert second.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_s3_72_05_a_cancelled_event_cannot_receive_an_approval(staff_api, booking):
    booking.event.status = EventStatus.CANCELLED
    booking.event.save(update_fields=["status"])

    assert staff_api.post(approve_url(booking), {}, format="json").status_code == 409
    assert_still_pending(booking)


@pytest.mark.django_db
def test_s3_72_05_a_reassigned_event_notifies_the_current_coordinator(
    staff_api, booking, second_coordinator
):
    booking.event.coordinator = second_coordinator
    booking.event.save(update_fields=["coordinator"])

    staff_api.post(approve_url(booking), {}, format="json")

    assert decision_notices().get().recipient == second_coordinator


@pytest.mark.django_db
def test_s3_72_05_a_failed_notice_leaves_no_partial_decision(booking, venue_staff):
    with (
        # Every notice is written by the shared SCRUM-79 writer's bulk_create.
        mock.patch.object(
            Notification.objects, "bulk_create", side_effect=RuntimeError("notification store down")
        ),
        pytest.raises(RuntimeError),
    ):
        approve_booking(booking, venue_staff)

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.decided_by is None
    assert VenueBookingHistory.objects.filter(booking=booking).count() == 1


@pytest.mark.django_db(transaction=True)
def test_s3_72_05_concurrent_approvals_of_overlapping_requests_cannot_both_succeed(
    organiser, coordinator, venue_staff, hall
):
    """Completes SCRUM-69 AC5 through the real SCRUM-72 approval action."""
    if connection.vendor != "postgresql":
        pytest.skip("Resource row locks require PostgreSQL")
    bookings = [pending(organiser, coordinator, hall) for _ in range(2)]
    barrier = Barrier(2)

    def approve(target):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                approve_booking(target, venue_staff)
                return "approved"
            except (BookingValidationError, VenueNotAvailable):
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(approve, bookings))

    assert results == ["approved", "refused"]
    assert VenueBooking.objects.filter(status=BookingStatus.APPROVED).count() == 1
    assert Notification.objects.filter(kind=NotificationKind.VENUE_DECIDED).count() == 1
