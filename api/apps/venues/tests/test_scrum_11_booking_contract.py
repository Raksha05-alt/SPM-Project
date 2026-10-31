"""SCRUM-11 venue booking contract - Sprint 3 gate G02.

This is the shared data and validation slice of SCRUM-11 (Request a venue
booking). It proves the booking record, its rules and its history. It does not
prove the coordinator's request journey: the real request action, assigned-
coordinator refusal (AC6), suitability refusal, staff inbox (AC4) and status
display (AC5) are built and tested at gate G09 in test_scrum_11_request_booking.py.

Case IDs follow the Sprint 3 guide: S3-SCRUM-11-<case>.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, transaction

from apps.core.statuses import EventStatus
from apps.venues.bookings import (
    BookingValidationError,
    InvalidBookingTransition,
    create_booking_record,
    transition_booking,
    validate_booking_request,
)
from apps.venues.models import BookingStatus, VenueBooking, VenueBookingHistory
from apps.venues.serializers import normalise_facilities
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
UTC = ZoneInfo("UTC")
START = datetime(2027, 3, 1, 10, 0, tzinfo=SGT)
END = datetime(2027, 3, 1, 12, 0, tzinfo=SGT)


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)


def request_values(for_event, at_venue, **overrides):
    values = {
        "event": for_event,
        "venue": at_venue,
        "starts_at": START,
        "ends_at": END,
        "attendance": 60,
        "layout": "THEATRE",
        "required_facilities": ["Video conferencing", "Hearing loop"],
        "wheelchair_access_required": True,
        "accessibility_notes": "Two wheelchair users; step-free route needed.",
    }
    values.update(overrides)
    return values


def book(for_event, at_venue, actor, **overrides):
    # Overrides may replace the event or venue itself, for example with None.
    return create_booking_record(
        requested_by=actor, **request_values(for_event, at_venue, **overrides)
    )


# S3-SCRUM-11-01 - AC1/AC2: the request's timing and requirements are stored exactly.


@pytest.mark.django_db
def test_s3_11_01_ac1_ac2_timing_and_requirements_are_saved_exactly(event, venue, coordinator):
    booking = book(event, venue, coordinator)

    fresh = VenueBooking.objects.get(pk=booking.pk)
    # 10:00-12:00 Singapore is 02:00-04:00 UTC: compare instants, not formatting.
    assert fresh.starts_at == datetime(2027, 3, 1, 2, 0, tzinfo=UTC)
    assert fresh.ends_at == datetime(2027, 3, 1, 4, 0, tzinfo=UTC)
    assert fresh.event == event
    assert fresh.venue == venue
    assert fresh.attendance == 60
    assert fresh.layout == "THEATRE"
    assert fresh.required_facilities == ["Video conferencing", "Hearing loop"]
    assert fresh.wheelchair_access_required is True
    assert fresh.accessibility_notes == "Two wheelchair users; step-free route needed."


@pytest.mark.django_db
def test_s3_11_01_a_new_request_is_pending_with_its_requester_and_time(event, venue, coordinator):
    booking = book(event, venue, coordinator)

    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.status == BookingStatus.PENDING
    assert fresh.requested_by == coordinator
    assert fresh.requested_at is not None
    assert fresh.decided_by is None
    assert fresh.decided_at is None
    history = list(VenueBookingHistory.objects.filter(booking=fresh))
    assert [(h.from_status, h.to_status, h.actor) for h in history] == [
        ("", BookingStatus.PENDING, coordinator)
    ]
    assert history[0].changed_at == fresh.requested_at


@pytest.mark.django_db
def test_s3_11_01_no_layout_preference_and_no_facilities_are_allowed(event, venue, coordinator):
    booking = book(
        event,
        venue,
        coordinator,
        layout="",
        required_facilities=[],
        wheelchair_access_required=False,
        accessibility_notes="",
    )

    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.layout == ""
    assert fresh.required_facilities == []
    assert fresh.wheelchair_access_required is False


@pytest.mark.django_db
def test_s3_11_01_facilities_are_tidied_exactly_as_venue_facilities_are(event, venue, coordinator):
    raw = ["  Video conferencing ", "video CONFERENCING", "", "Hearing loop"]

    booking = book(event, venue, coordinator, required_facilities=raw)

    assert booking.required_facilities == ["Video conferencing", "Hearing loop"]
    assert booking.required_facilities == normalise_facilities(raw)


@pytest.mark.django_db
def test_s3_11_01_accessibility_notes_are_kept_for_staff_without_surrounding_space(
    event, venue, coordinator
):
    booking = book(event, venue, coordinator, accessibility_notes="  Hearing loop at front.  ")

    assert booking.accessibility_notes == "Hearing loop at front."


# S3-SCRUM-11-02 - AC3: missing or invalid information is refused, item by item.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"starts_at": None}, "starts_at"),
        ({"ends_at": None}, "ends_at"),
        ({"ends_at": START}, "ends_at"),
        ({"ends_at": START - timedelta(minutes=1)}, "ends_at"),
        ({"starts_at": datetime(2027, 3, 1, 10, 0)}, "starts_at"),
        ({"ends_at": "2027-03-01T12:00"}, "ends_at"),
        ({"attendance": None}, "attendance"),
        ({"attendance": 0}, "attendance"),
        ({"attendance": -5}, "attendance"),
        ({"attendance": 2.5}, "attendance"),
        ({"attendance": "60"}, "attendance"),
        ({"attendance": True}, "attendance"),
        ({"layout": "CABARET"}, "layout"),
        ({"layout": "theatre"}, "layout"),
        ({"required_facilities": "Projector"}, "required_facilities"),
        ({"required_facilities": [1, 2]}, "required_facilities"),
        ({"wheelchair_access_required": "yes"}, "wheelchair_access_required"),
        ({"accessibility_notes": None}, "accessibility_notes"),
        ({"venue": None}, "venue"),
        ({"event": None}, "event"),
    ],
)
def test_s3_11_02_ac3_invalid_information_is_refused_and_nothing_is_saved(
    event, venue, coordinator, overrides, field
):
    with pytest.raises(BookingValidationError) as raised:
        book(event, venue, coordinator, **overrides)

    assert field in raised.value.errors
    assert not VenueBooking.objects.exists()
    assert not VenueBookingHistory.objects.exists()


@pytest.mark.django_db
def test_s3_11_02_ac3_every_missing_item_is_identified_at_once(event, venue):
    with pytest.raises(BookingValidationError) as raised:
        validate_booking_request(
            event=event,
            venue=None,
            starts_at=None,
            ends_at=None,
            attendance=None,
            layout="CABARET",
        )

    assert set(raised.value.errors) == {"venue", "starts_at", "ends_at", "attendance", "layout"}


@pytest.mark.django_db
def test_s3_11_02_ac3_a_one_minute_booking_is_valid(event, venue, coordinator):
    booking = book(event, venue, coordinator, ends_at=START + timedelta(minutes=1))

    assert booking.ends_at - booking.starts_at == timedelta(minutes=1)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.DRAFT, EventStatus.REJECTED, EventStatus.CANCELLED, EventStatus.COMPLETED],
)
def test_s3_11_02_a_venue_cannot_be_requested_for_a_draft_or_finished_event(
    organiser, coordinator, venue, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    with pytest.raises(BookingValidationError) as raised:
        book(event, venue, coordinator)

    assert "event" in raised.value.errors
    assert not VenueBooking.objects.exists()


# Database rules - hold even if a later action forgets a check.


def _row(event, venue, **overrides):
    data = {
        "event": event,
        "venue": venue,
        "starts_at": START,
        "ends_at": END,
        "attendance": 60,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"ends_at": START},
        {"ends_at": START - timedelta(hours=1)},
        {"attendance": 0},
        {"status": BookingStatus.REJECTED, "decision_reason": ""},
    ],
)
def test_the_database_refuses_an_invalid_booking_row(event, venue, overrides):
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueBooking.objects.create(**_row(event, venue, **overrides))


@pytest.mark.django_db
def test_the_database_allows_only_one_approved_venue_per_event(event, venue):
    other = make_venue(name="Garden Room")
    VenueBooking.objects.create(**_row(event, venue, status=BookingStatus.APPROVED))

    with pytest.raises(IntegrityError), transaction.atomic():
        VenueBooking.objects.create(**_row(event, other, status=BookingStatus.APPROVED))

    # Further Pending requests for the same event remain possible.
    VenueBooking.objects.create(**_row(event, other))
    assert VenueBooking.objects.filter(event=event).count() == 2


@pytest.mark.django_db
def test_an_event_or_venue_with_bookings_cannot_be_deleted(event, venue, coordinator):
    from django.db.models import ProtectedError

    book(event, venue, coordinator)

    with pytest.raises(ProtectedError):
        venue.delete()
    with pytest.raises(ProtectedError):
        event.delete()


# Status and history contract used by SCRUM-72 decisions and SCRUM-67 withdrawal.


@pytest.mark.django_db
def test_approval_records_the_decider_time_and_history(event, venue, coordinator, venue_staff):
    booking = book(event, venue, coordinator)

    transition_booking(booking, BookingStatus.APPROVED, venue_staff)

    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.status == BookingStatus.APPROVED
    assert fresh.decided_by == venue_staff
    assert fresh.decided_at == fresh.status_changed_at
    last = VenueBookingHistory.objects.filter(booking=fresh).last()
    assert (last.from_status, last.to_status, last.actor) == (
        BookingStatus.PENDING,
        BookingStatus.APPROVED,
        venue_staff,
    )
    assert last.changed_at == fresh.status_changed_at


@pytest.mark.django_db
def test_a_rejection_keeps_its_reason(event, venue, coordinator, venue_staff):
    booking = book(event, venue, coordinator)

    transition_booking(booking, BookingStatus.REJECTED, venue_staff, "  Under renovation.  ")

    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.status == BookingStatus.REJECTED
    assert fresh.decision_reason == "Under renovation."
    assert fresh.history.last().reason == "Under renovation."


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["", "   "])
def test_a_rejection_without_a_reason_is_refused_and_nothing_changes(
    event, venue, coordinator, venue_staff, reason
):
    booking = book(event, venue, coordinator)

    with pytest.raises(BookingValidationError) as raised:
        transition_booking(booking, BookingStatus.REJECTED, venue_staff, reason)

    assert "reason" in raised.value.errors
    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.status == BookingStatus.PENDING
    assert fresh.history.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("start", [BookingStatus.PENDING, BookingStatus.APPROVED])
def test_pending_and_approved_bookings_can_be_withdrawn_keeping_the_decision(
    event, venue, coordinator, venue_staff, start
):
    booking = book(event, venue, coordinator)
    if start == BookingStatus.APPROVED:
        transition_booking(booking, BookingStatus.APPROVED, venue_staff)

    transition_booking(booking, BookingStatus.WITHDRAWN, coordinator, "Event moved online.")

    fresh = VenueBooking.objects.get(pk=booking.pk)
    assert fresh.status == BookingStatus.WITHDRAWN
    assert fresh.history.last().actor == coordinator
    assert fresh.history.last().reason == "Event moved online."
    if start == BookingStatus.APPROVED:
        assert fresh.decided_by == venue_staff


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, target",
    [
        ([BookingStatus.REJECTED], BookingStatus.APPROVED),
        ([BookingStatus.REJECTED], BookingStatus.WITHDRAWN),
        ([BookingStatus.WITHDRAWN], BookingStatus.APPROVED),
        ([BookingStatus.WITHDRAWN], BookingStatus.WITHDRAWN),
        ([BookingStatus.APPROVED], BookingStatus.REJECTED),
        ([BookingStatus.APPROVED], BookingStatus.APPROVED),
        ([], BookingStatus.PENDING),
    ],
)
def test_a_move_the_lifecycle_does_not_allow_is_refused_and_nothing_changes(
    event, venue, coordinator, venue_staff, path, target
):
    booking = book(event, venue, coordinator)
    for step in path:
        transition_booking(booking, step, venue_staff, "Recorded reason.")
    before = VenueBooking.objects.get(pk=booking.pk)
    history_before = before.history.count()

    with pytest.raises(InvalidBookingTransition):
        transition_booking(booking, target, venue_staff, "Another reason.")

    after = VenueBooking.objects.get(pk=booking.pk)
    assert after.status == before.status
    assert after.decision_reason == before.decision_reason
    assert after.history.count() == history_before


@pytest.mark.django_db
def test_a_later_request_does_not_overwrite_an_earlier_decision(
    event, venue, coordinator, venue_staff
):
    first = book(event, venue, coordinator)
    transition_booking(first, BookingStatus.REJECTED, venue_staff, "Clashes with maintenance.")

    second = book(event, venue, coordinator, attendance=40)

    assert second.pk != first.pk
    first.refresh_from_db()
    assert first.status == BookingStatus.REJECTED
    assert first.decision_reason == "Clashes with maintenance."
    assert VenueBooking.objects.filter(event=event, venue=venue).count() == 2


# Occupancy contract consumed by SCRUM-69 (Adilah) - Approved bookings only, half-open.


@pytest.mark.django_db
def test_only_approved_bookings_occupy_a_venue(event, venue, coordinator, venue_staff):
    pending = book(event, venue, coordinator)
    approved_event = make_event(event.created_by, status=EventStatus.APPROVED)
    approved = book(approved_event, venue, coordinator)
    transition_booking(approved, BookingStatus.APPROVED, venue_staff)
    rejected_event = make_event(event.created_by, status=EventStatus.APPROVED)
    rejected = book(rejected_event, venue, coordinator)
    transition_booking(rejected, BookingStatus.REJECTED, venue_staff, "No.")

    occupying = set(VenueBooking.objects.occupying().values_list("pk", flat=True))

    assert occupying == {approved.pk}
    assert pending.pk not in occupying


@pytest.mark.django_db
@pytest.mark.parametrize(
    "start, end, overlaps",
    [
        ((8, 0), (10, 0), False),  # ends exactly as the booking starts: adjacent
        ((12, 0), (13, 0), False),  # starts exactly as the booking ends: adjacent
        ((9, 0), (10, 1), True),
        ((11, 59), (13, 0), True),
        ((10, 30), (11, 0), True),
        ((9, 0), (13, 0), True),
    ],
)
def test_overlap_uses_half_open_periods(event, venue, coordinator, start, end, overlaps):
    booking = book(event, venue, coordinator)
    period_start = datetime(2027, 3, 1, *start, tzinfo=SGT)
    period_end = datetime(2027, 3, 1, *end, tzinfo=SGT)

    found = VenueBooking.objects.overlapping(period_start, period_end)

    assert (booking in found) is overlaps


@pytest.mark.django_db
def test_bookings_and_their_history_describe_themselves_for_staff_screens(
    event, venue, coordinator
):
    booking = book(event, venue, coordinator)

    assert str(booking) == f"Booking {booking.pk}: event {event.pk} at venue {venue.pk} [PENDING]"
    assert str(booking.history.get()) == f"Booking {booking.pk}: new -> PENDING"
