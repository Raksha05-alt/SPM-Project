"""SCRUM-66 - re-check suitability when the event changes.

The venue is requested and approved through the real SCRUM-11/72 actions
(``approve_venue``), and the coordinator changes the event through the real
SCRUM-61 edit endpoint, PATCH /api/events/<id>/. Harbour Hall: capacity 200,
layouts Theatre and Banquet, wheelchair access recorded as available.

AC5 uses SCRUM-87's session bookings to verify that the main programme
follows event attendance while breakout bookings keep their own attendance.
"""

from unittest import mock

import pytest

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.events.impact import booking_attendance, impact_of, is_main, record_reviews
from apps.events.models import VenueReview
from apps.notifications.models import Notification, NotificationKind, NotificationTarget
from apps.safety.tests.conftest import approve_venue, make_venue
from apps.safety.tests.conftest import planning_event as planning_event  # noqa: F401
from apps.safety.tests.conftest import venue as venue  # noqa: F401
from apps.venues.bookings import approve_booking, request_booking, withdraw_booking
from apps.venues.models import BookingStatus, Venue
from apps.venues.suitability import Requirement
from conftest import _make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def booked(planning_event, venue, venue_staff):
    """A Planning event (120 attending, Theatre) with Harbour Hall approved."""
    booking = approve_venue(planning_event, venue, venue_staff)
    planning_event.refresh_from_db()
    return planning_event, booking


def edit(api, coordinator, event, **changes):
    api.force_authenticate(coordinator)
    response = api.patch(f"/api/events/{event.pk}/", changes, format="json")
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    return response


def reviews_url(event):
    return f"/api/events/{event.pk}/venue-reviews/"


def open_review(booking):
    return VenueReview.objects.get(booking=booking, resolved_at__isnull=True)


def review_notices():
    return Notification.objects.filter(kind=NotificationKind.VENUE_REVIEW)


# --------------------------------------------------------------------------
# AC1 - attendance beyond capacity flags the booking and notifies me
# --------------------------------------------------------------------------


def test_ac1a_attendance_equal_to_capacity_raises_no_flag(api, booked, coordinator):
    event, booking = booked

    edit(api, coordinator, event, expected_attendance=200)

    assert not VenueReview.objects.exists()
    assert not review_notices().exists()


def test_ac1b_attendance_beyond_capacity_flags_the_booking_and_notifies_the_coordinator(
    api, booked, coordinator
):
    event, booking = booked

    edit(api, coordinator, event, expected_attendance=201)

    review = open_review(booking)
    assert review.reasons == [
        {
            "requirement": Requirement.CAPACITY,
            "message": "Expected attendance of 201 exceeds the venue's maximum capacity of 200.",
        }
    ]
    assert review.changed_fields == ["expected_attendance"]
    assert review.raised_by == coordinator
    [notice] = review_notices()
    assert notice.recipient == coordinator
    assert (notice.target_type, notice.target_id) == (NotificationTarget.VENUE_BOOKING, booking.pk)
    assert "Harbour Hall needs review" in notice.message
    assert "201" in notice.message
    # The booking itself is never changed or released by a review.
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


def test_ac1c_saving_the_same_problem_again_does_not_notify_again(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)

    # A save that leaves attendance alone does not re-check it ...
    edit(api, coordinator, event, expected_attendance=201, name="Renamed conference")
    # ... and recording the same outcome again (a replay) opens nothing new.
    impacts = impact_of(event, {"expected_attendance": 201}, changed={"expected_attendance"})
    assert record_reviews(event, impacts, coordinator) == []

    assert VenueReview.objects.count() == 1
    assert review_notices().count() == 1


def test_ac1d_a_worse_change_replaces_the_review_and_notifies_again(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)
    first = open_review(booking)

    edit(api, coordinator, event, expected_attendance=250)

    first.refresh_from_db()
    assert first.resolved_at is not None and first.resolution == "Replaced by a newer review."
    assert "250" in open_review(booking).reasons[0]["message"]
    assert review_notices().count() == 2


def test_ac1e_reducing_attendance_again_resolves_the_review(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)

    edit(api, coordinator, event, expected_attendance=180)

    review = VenueReview.objects.get()
    assert review.resolved_at is not None
    assert review.resolved_by == coordinator
    assert review.resolution == "A later change means the venue suits the event again."
    assert review_notices().count() == 1


# --------------------------------------------------------------------------
# AC2 - layout or accessibility needs the venue does not support
# --------------------------------------------------------------------------


def test_ac2a_an_unsupported_layout_flags_the_booking(api, booked, coordinator):
    event, booking = booked

    edit(api, coordinator, event, required_layout="CLASSROOM")

    [reason] = open_review(booking).reasons
    assert reason == {
        "requirement": Requirement.LAYOUT,
        "message": "The venue does not support the required Classroom layout.",
    }
    assert review_notices().count() == 1


def test_ac2b_a_supported_layout_raises_no_flag(api, booked, coordinator):
    event, booking = booked

    edit(api, coordinator, event, required_layout="BANQUET")

    assert not VenueReview.objects.exists()


@pytest.mark.parametrize(
    ("wheelchair_access", "message"),
    [
        (False, "The venue does not have the required wheelchair access."),
        (None, "The venue's wheelchair access is not recorded, so it cannot be confirmed."),
    ],
)
def test_ac2c_new_accessibility_needs_flag_a_venue_without_confirmed_access(
    api, booked, coordinator, wheelchair_access, message
):
    event, booking = booked
    Venue.objects.filter(pk=booking.venue_id).update(wheelchair_access=wheelchair_access)

    edit(api, coordinator, event, accessibility_needs="Three wheelchair users and a guide dog.")

    assert open_review(booking).reasons == [
        {"requirement": Requirement.ACCESSIBILITY, "message": message}
    ]


def test_ac2d_accessibility_needs_at_a_venue_with_confirmed_access_raise_no_flag(
    api, booked, coordinator
):
    event, booking = booked  # Harbour Hall records wheelchair access as available.

    edit(api, coordinator, event, accessibility_needs="Three wheelchair users.")

    assert not VenueReview.objects.exists()


def test_ac2e_an_accessibility_flag_stays_while_other_requirements_change(api, booked, coordinator):
    event, booking = booked
    Venue.objects.filter(pk=booking.venue_id).update(wheelchair_access=False)
    edit(api, coordinator, event, accessibility_needs="A wheelchair user and a hearing loop.")
    assert open_review(booking).reasons[0]["requirement"] == Requirement.ACCESSIBILITY

    # A later, harmless attendance change must not clear the accessibility problem.
    edit(api, coordinator, event, expected_attendance=150)

    reasons = open_review(booking).reasons
    assert [r["requirement"] for r in reasons] == [Requirement.ACCESSIBILITY]
    assert review_notices().count() == 1


# --------------------------------------------------------------------------
# AC3 - the reason is visible when I open the event
# --------------------------------------------------------------------------


def test_ac3a_the_event_shows_why_the_booking_was_flagged(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)

    data = api.get(reviews_url(event)).data

    [review] = data["open"]
    assert review["booking"] == booking.pk
    assert review["venue"] == "Harbour Hall"
    assert review["reasons"][0]["message"] == (
        "Expected attendance of 201 exceeds the venue's maximum capacity of 200."
    )
    assert review["raised_by_name"] == "Cora Coordinator"
    assert review["raised_at"]
    assert data["history"] == []


def test_ac3b_an_open_review_blocks_confirmation_and_names_the_reason(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)

    readiness = api.get(f"/api/events/{event.pk}/readiness/").data
    response = api.post(f"/api/events/{event.pk}/confirm/", {}, format="json")

    expected = (
        "Venue: Harbour Hall needs review after the event changed. Expected attendance of "
        "201 exceeds the venue's maximum capacity of 200."
    )
    assert expected in str(readiness)
    assert response.status_code == 409
    assert expected in str(response.data)


def test_ac3b2_a_safety_check_cannot_be_requested_while_a_venue_needs_review(
    api, booked, coordinator
):
    event, _ = booked
    edit(api, coordinator, event, expected_attendance=201)

    data = api.get(f"/api/events/{event.pk}/safety-checks/").data

    assert data["can_request"] is False
    assert any("Harbour Hall needs review" in gap for gap in data["arrangement_gaps"])


def test_ac3c_resolved_reviews_stay_on_record(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)
    edit(api, coordinator, event, expected_attendance=150)

    data = api.get(reviews_url(event)).data

    assert data["open"] == []
    [past] = data["history"]
    assert past["resolution"] == "A later change means the venue suits the event again."


@pytest.mark.parametrize("role", [Role.EVENT_COORDINATOR_LEAD, Role.VENUE_STAFF])
def test_ac3d_leads_and_venue_staff_can_read_the_reasons(api, booked, role):
    event, _ = booked
    api.force_authenticate(_make_user(f"{role.lower()}2@x.example", role))

    assert api.get(reviews_url(event)).status_code == 200


@pytest.mark.parametrize(
    "role",
    [Role.EVENT_ORGANISER, Role.ATTENDEE, Role.TECHNICAL_SUPPORT, Role.SAFETY_OFFICER],
)
def test_ac3e_other_roles_are_refused_and_audited(api, booked, role, acme):
    event, _ = booked
    user = _make_user(
        f"{role.lower()}2@x.example", role, acme if role == Role.EVENT_ORGANISER else None
    )
    api.force_authenticate(user)

    assert api.get(reviews_url(event)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


def test_ac3f_another_coordinator_is_refused_and_audited(api, booked, second_coordinator):
    event, _ = booked
    api.force_authenticate(second_coordinator)

    assert api.get(reviews_url(event)).status_code == 403
    assert AuditLog.objects.filter(
        actor=second_coordinator, detail="event is not assigned to this coordinator"
    ).exists()


# --------------------------------------------------------------------------
# AC4 - a change that does not affect suitability raises no flag
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Partner Summit 2027"},
        {"purpose": "Annual partner briefing"},
        {"description": "Keynote and panels."},
        {"equipment_notes": "Two lapel microphones."},
        {"registration_required": True},
        {"expected_attendance": 150},
    ],
    ids=["name", "purpose", "description", "equipment-notes", "registration", "attendance-150"],
)
def test_ac4a_harmless_changes_raise_no_flag_or_notice(api, booked, coordinator, changes):
    event, _ = booked

    edit(api, coordinator, event, **changes)

    assert not VenueReview.objects.exists()
    assert not review_notices().exists()


def test_ac4b_only_approved_bookings_are_rechecked(api, planning_event, venue, coordinator):
    request_booking(
        event=planning_event,
        venue=venue,
        requested_by=coordinator,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=120,
        layout="THEATRE",
    )

    edit(api, coordinator, planning_event, expected_attendance=500)

    # A Pending request is rechecked by Venue Staff's approval (SCRUM-72) instead.
    assert not VenueReview.objects.exists()


# --------------------------------------------------------------------------
# Lifecycle, preview and atomicity
# --------------------------------------------------------------------------


def test_l1_withdrawing_the_booking_closes_its_review(api, booked, coordinator):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=201)

    withdraw_booking(
        booking=booking,
        actor=coordinator,
        expected_status=BookingStatus.APPROVED,
        confirm_release=True,
    )

    review = VenueReview.objects.get()
    assert review.resolved_at is not None
    assert review.resolved_by == coordinator
    assert review.resolution == "The booking was withdrawn."
    assert api.get(reviews_url(event)).data["open"] == []


def test_l2_a_replacement_venue_that_fits_clears_the_way_to_confirm(
    api, booked, coordinator, venue_staff
):
    event, booking = booked
    edit(api, coordinator, event, expected_attendance=300)
    withdraw_booking(
        booking=booking,
        actor=coordinator,
        expected_status=BookingStatus.APPROVED,
        confirm_release=True,
    )

    approve_venue(event, make_venue("Grand Ballroom", capacity=400), venue_staff, attendance=300)

    readiness = str(api.get(f"/api/events/{event.pk}/readiness/").data)
    assert "needs review" not in readiness


def test_l3_impact_of_previews_without_writing_anything(booked):
    event, booking = booked

    [impact] = impact_of(event, {"expected_attendance": 500, "name": "Ignored"})

    assert impact.booking == booking and impact.unsuitable
    assert impact.rechecked_for == ["expected_attendance"]
    assert impact.as_dict()["reasons"][0]["requirement"] == Requirement.CAPACITY
    assert impact_of(event, {"name": "Only a name"}) == []
    assert impact_of(event, {"expected_attendance": 120}) == []
    assert not VenueReview.objects.exists()
    assert not review_notices().exists()


def test_l4_a_failed_notice_rolls_the_edit_and_review_back(api, booked, coordinator):
    event, _ = booked
    api.force_authenticate(coordinator)

    with (
        mock.patch(
            "apps.events.impact.notify", side_effect=RuntimeError("notification store down")
        ),
        pytest.raises(RuntimeError),
    ):
        api.patch(f"/api/events/{event.pk}/", {"expected_attendance": 201}, format="json")

    event.refresh_from_db()
    assert event.expected_attendance == 120
    assert not VenueReview.objects.exists()


def test_l5_one_open_review_per_booking_is_enforced(booked, coordinator):
    from django.db import IntegrityError, transaction

    event, booking = booked
    VenueReview.objects.create(event=event, booking=booking, reasons=[{"m": 1}])

    with pytest.raises(IntegrityError), transaction.atomic():
        VenueReview.objects.create(event=event, booking=booking, reasons=[{"m": 2}])


def test_l6_record_reviews_with_nothing_unsuitable_and_nothing_open_does_nothing(
    booked, coordinator
):
    event, _ = booked
    impacts = impact_of(event, {"expected_attendance": 150})

    assert impacts and not impacts[0].unsuitable
    assert record_reviews(event, impacts, coordinator) == []
    assert not VenueReview.objects.exists()


def test_l7_every_booking_is_the_main_programme_until_sessions_exist(booked):
    _, booking = booked

    assert is_main(booking) is True
    assert booking_attendance(booking, 321) == 321


def test_ac5_attendance_change_flags_only_the_main_programme(api, booked, coordinator, venue_staff):
    event, main = booked
    breakout_room = make_venue("Breakout room", capacity=30)
    breakout = approve_booking(
        request_booking(
            event=event,
            venue=breakout_room,
            requested_by=coordinator,
            starts_at=event.preferred_start,
            ends_at=event.preferred_end,
            attendance=30,
            layout="THEATRE",
            session_kind="BREAKOUT",
            session_name="Breakout A",
        ),
        venue_staff,
    )

    edit(api, coordinator, event, expected_attendance=201)

    assert open_review(main).reasons == [
        {
            "requirement": Requirement.CAPACITY,
            "message": "Expected attendance of 201 exceeds the venue's maximum capacity of 200.",
        }
    ]
    assert not VenueReview.objects.filter(booking=breakout).exists()
    breakout.refresh_from_db()
    assert breakout.attendance == 30
    assert breakout.status == BookingStatus.APPROVED
    assert list(review_notices().values_list("target_id", flat=True)) == [main.pk]


def test_clearing_event_accessibility_needs_resolves_the_review(api, booked, coordinator):
    event, booking = booked
    Venue.objects.filter(pk=booking.venue_id).update(wheelchair_access=False)
    edit(api, coordinator, event, accessibility_needs="Wheelchair access for two guests.")
    review = open_review(booking)

    edit(api, coordinator, event, accessibility_needs="")

    review.refresh_from_db()
    assert review.resolved_at is not None
    assert not VenueReview.objects.filter(booking=booking, resolved_at__isnull=True).exists()
    assert review_notices().count() == 1
