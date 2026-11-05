"""SCRUM-80 - Apply an approved change through staff review (Sprint 4 gate APPLY).

As an Event Coordinator, I want staff to review and update each arrangement
affected by an approved change, so that ConnectSphere does not replace
confirmed bookings or reservations without a decision.

Week 7 changes 3 and 6: only the affected venue goes back through approval, and
any change to the arrangements requires a new Operational Safety Check before
the event is confirmed again.

The arrangements are made through real actions: the venue booking requested
and approved by Venue Staff, the equipment requested by the coordinator and
reserved by Technical Support, attendee registrations, the organiser's change
request and the coordinator's approval (SCRUM-78). The Confirmed status is a
labelled low-level fixture (real confirmation needs the whole Safety flow).

Case IDs follow the Sprint 4 guide: S4-80-<case>.
"""

import datetime
from unittest import mock

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentType,
    TechnicalApproval,
    TechnicalApprovalStatus,
)
from apps.equipment.reservations import reserve
from apps.equipment.services import create_request
from apps.events.change_requests import decide_change
from apps.events.impact import ApplyRefused, apply_change, review_arrangement
from apps.events.models import (
    ArrangementOutcome,
    ArrangementReview,
    ChangeRequestStatus,
    ChangeSource,
    EventFieldChange,
    VenuePeriodReview,
)
from apps.events.tests.test_scrum_78_review_change import (
    END,
    NEXT_DAY,
    START,
    approved_booking,
    attendee_named,
    change_for,
    hall,
    mark_confirmed,
    open_registration,
    planning_event,
)
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.services import register
from apps.safety.models import SafetyStatus
from apps.safety.services import arrangement_gaps
from apps.safety.tests.conftest import make_check
from apps.venues.models import BookingStatus, VenueBooking, VenueBookingHistory
from conftest import make_event


@pytest.fixture
def tech(db):
    return User.objects.create_user(
        username="tech@example.com", email="tech@example.com", role=Role.TECHNICAL_SUPPORT
    )


@pytest.fixture
def venue(db):
    return hall()


@pytest.fixture
def gala(organiser, coordinator, venue_staff, tech, venue):
    """Confirmed 'Annual Gala': Harbour Hall approved, 3 projectors reserved and approved, 2 registered."""
    event = planning_event(organiser, coordinator, venue_staff, venue)
    projector = EquipmentType.objects.create(code="PROJECTOR", name="Projector", total_quantity=10)
    line = create_request(
        event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=3
    )
    plan = EquipmentPlan.objects.get(event=event)
    # Technical Support reserve it; the fully reserved plan is approved by reserve().
    reserve(equipment_request=line, actor=tech, expected_revision=plan.revision)
    mark_confirmed(event)
    open_registration(event)
    for email in ("amy@example.com", "ben@example.com"):
        register(event=event, attendee=attendee_named(email), full_name=email, email=email)
    event.refresh_from_db()
    return event


def approved_change(event, organiser, coordinator, **proposed):
    """The organiser's request, approved by the coordinator through SCRUM-78."""
    change = change_for(event, organiser, **proposed)
    decided, _ = decide_change(
        change=change, actor=coordinator, decision="APPROVE", reason="Agreed."
    )
    return decided


def move_one_day(event, organiser, coordinator):
    return approved_change(
        event,
        organiser,
        coordinator,
        preferred_start=START + NEXT_DAY,
        preferred_end=END + NEXT_DAY,
    )


def apply_url(change):
    return f"/api/change-requests/{change.pk}/apply/"


def decide_url(review):
    return f"/api/arrangement-reviews/{review.pk}/decide/"


def outcome_of(api, user, review, outcome="ACCOMMODATED", reason="We can do the new date."):
    """Staff record an outcome on their own client, so the test's client keeps its user."""
    from rest_framework.test import APIClient

    staff = APIClient()
    staff.force_authenticate(user)
    return staff.post(decide_url(review), {"outcome": outcome, "reason": reason}, format="json")


def arrangements(event):
    booking = VenueBooking.objects.get(event=event)
    reservation = EquipmentPlan.objects.get(event=event).requests.get().reservations.active().get()
    event.refresh_from_db()
    return (
        (booking.status, booking.starts_at, booking.ends_at, booking.attendance),
        (reservation.starts_at, reservation.ends_at, reservation.quantity),
        (event.preferred_start, event.preferred_end, event.expected_attendance),
    )


def at(value):
    """A stored ISO 8601 timestamp as an instant (compare instants, not formatting)."""
    return datetime.datetime.fromisoformat(value)


def kinds(change):
    return sorted(change.arrangement_reviews.values_list("kind", flat=True))


@pytest.fixture
def coordinator_api(api, coordinator):
    api.force_authenticate(coordinator)
    return api


# S4-80-01 - AC1: each affected arrangement is listed for staff review; nothing moves.


@pytest.mark.django_db
def test_s4_80_01_ac1_applying_lists_each_affected_arrangement_for_review(
    coordinator_api, organiser, coordinator, gala
):
    change = move_one_day(gala, organiser, coordinator)
    before = arrangements(gala)

    response = coordinator_api.post(apply_url(change))

    assert response.status_code == 200
    assert response.data["detail"].startswith("2 arrangement(s) sent to staff for review.")
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.IN_REVIEW
    assert (change.applied_by, change.applied_at is not None) == (coordinator, True)
    assert kinds(change) == ["EQUIPMENT", "VENUE"]
    venue_review = change.arrangement_reviews.get(kind="VENUE")
    assert at(venue_review.proposed["starts_at"]) == START + NEXT_DAY
    assert at(venue_review.before["starts_at"]) == START
    # The originals are untouched until staff accept the revised arrangement.
    assert arrangements(gala) == before


@pytest.mark.django_db
def test_s4_80_01_ac1_venue_staff_and_technical_support_are_told(
    coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)

    coordinator_api.post(apply_url(change))

    notices = Notification.objects.filter(kind=NotificationKind.CHANGE_REVIEW)
    assert sorted(n.recipient_id for n in notices) == sorted([venue_staff.pk, tech.pk])
    assert notices.first().message.endswith(
        "The current arrangement stays until every review is recorded."
    )


@pytest.mark.django_db
def test_s4_80_01_ac1_each_staff_inbox_holds_only_its_own_reviews(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))

    api.force_authenticate(venue_staff)
    venue_rows = api.get("/api/arrangement-reviews/").data
    api.force_authenticate(tech)
    tech_rows = api.get("/api/arrangement-reviews/").data

    assert [(r["kind"], r["name"], r["event_name"]) for r in venue_rows] == [
        ("VENUE", "Harbour Hall", "Annual Gala")
    ]
    assert [(r["kind"], r["name"], r["quantity"]) for r in tech_rows] == [
        ("EQUIPMENT", "Projector", 3)
    ]
    assert api.get("/api/arrangement-reviews/?status=BOGUS").status_code == 400
    assert api.get("/api/arrangement-reviews/?status=ACCOMMODATED").data == []


@pytest.mark.django_db
def test_s4_80_01_scrum_70_and_66_reviews_are_recorded_through_the_real_producer(
    coordinator_api, organiser, coordinator, gala
):
    change = approved_change(
        gala,
        organiser,
        coordinator,
        preferred_start=START + NEXT_DAY,
        preferred_end=END + NEXT_DAY,
        expected_attendance=151,
    )

    coordinator_api.post(apply_url(change))

    [period] = VenuePeriodReview.objects.filter(change_request=change)
    assert (period.starts_at, period.reviewed_at) == (START + NEXT_DAY, None)
    review = gala.venue_reviews.get()
    assert review.source == ChangeSource.CHANGE_REQUEST
    assert review.resolved_at is None


@pytest.mark.django_db
def test_s4_80_01_a_change_affecting_no_arrangement_is_applied_at_once(
    coordinator_api, organiser, coordinator, gala
):
    change = approved_change(gala, organiser, coordinator, name="Annual Gala 2027")

    response = coordinator_api.post(apply_url(change))

    assert (
        response.data["detail"]
        == "The change affected no existing arrangement and has been applied."
    )
    change.refresh_from_db()
    gala.refresh_from_db()
    assert (change.status, gala.name) == (ChangeRequestStatus.APPLIED, "Annual Gala 2027")
    [entry] = EventFieldChange.objects.filter(event=gala, source=ChangeSource.CHANGE_REQUEST)
    assert (entry.field, entry.before, entry.after) == ("name", "Annual Gala", "Annual Gala 2027")


@pytest.mark.django_db
@pytest.mark.parametrize("decision", [None, "REJECT"], ids=["pending", "rejected"])
def test_s4_80_01_only_an_approved_change_is_applied(
    coordinator_api, organiser, coordinator, gala, decision
):
    change = change_for(gala, organiser, expected_attendance=140)
    if decision:
        decide_change(change=change, actor=coordinator, decision=decision, reason="No.")

    response = coordinator_api.post(apply_url(change))

    assert response.status_code == 409
    assert response.data["detail"].startswith("Only an approved change can be applied")


@pytest.mark.django_db
def test_s4_80_01_applying_twice_is_refused(coordinator_api, organiser, coordinator, gala):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))

    response = coordinator_api.post(apply_url(change))

    assert response.status_code == 409
    assert ArrangementReview.objects.filter(change_request=change).count() == 2


@pytest.mark.django_db
def test_s4_80_01_a_stale_change_is_not_applied(coordinator_api, organiser, coordinator, gala):
    change = move_one_day(gala, organiser, coordinator)
    type(gala).objects.filter(pk=gala.pk).update(description="Edited since")

    response = coordinator_api.post(apply_url(change))

    assert response.status_code == 409
    assert response.data["assessment"]["stale"] is True
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.APPROVED
    assert not ArrangementReview.objects.exists()


@pytest.mark.django_db
def test_s4_80_01_a_finished_event_takes_no_change(coordinator_api, organiser, coordinator, gala):
    change = move_one_day(gala, organiser, coordinator)
    type(gala).objects.filter(pk=gala.pk).update(status=EventStatus.CANCELLED)

    response = coordinator_api.post(apply_url(change))

    assert response.status_code == 409
    assert response.data["detail"] == "A Cancelled event cannot take a change."


@pytest.mark.django_db
def test_s4_80_01_only_the_assigned_coordinator_applies(
    api, organiser, coordinator, second_coordinator, gala
):
    change = move_one_day(gala, organiser, coordinator)
    type(gala).objects.filter(pk=gala.pk).update(coordinator=second_coordinator)
    api.force_authenticate(coordinator)

    assert api.post(apply_url(change)).status_code == 403
    api.force_authenticate(organiser)
    assert api.post(apply_url(change)).status_code == 403


@pytest.mark.django_db
def test_s4_80_01_a_refusal_found_under_the_lock_is_audited(
    coordinator_api, organiser, coordinator, gala
):
    from apps.events.change_requests import NotAssignedCoordinator

    change = move_one_day(gala, organiser, coordinator)
    with mock.patch("apps.events.change_views.apply_change", side_effect=NotAssignedCoordinator):
        assert coordinator_api.post(apply_url(change)).status_code == 403
    assert AuditLog.objects.filter(
        actor=coordinator, allowed=False, detail="only the assigned coordinator may apply a change"
    ).exists()


# S4-80-02 - AC2: staff accommodate; the revised arrangement, who and when are recorded.


@pytest.mark.django_db
def test_s4_80_02_ac2_one_accommodation_records_who_and_when_but_switches_nothing(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    before = arrangements(gala)
    review = change.arrangement_reviews.get(kind="VENUE")

    response = outcome_of(api, venue_staff, review)

    assert response.status_code == 200
    assert response.data["detail"] == "Your outcome has been recorded."
    review.refresh_from_db()
    assert (review.outcome, review.reviewed_by, review.review_reason) == (
        ArrangementOutcome.ACCOMMODATED,
        venue_staff,
        "We can do the new date.",
    )
    assert review.reviewed_at is not None
    # SCRUM-70's staff-outcome callback recorded the fresh period check too.
    assert VenuePeriodReview.objects.get(change_request=change).reviewed_by == venue_staff
    # Technical Support has not reviewed yet: nothing switches.
    assert arrangements(gala) == before


@pytest.mark.django_db
def test_s4_80_02_ac2_the_last_accommodation_switches_everything_together(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))

    response = outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert (
        response.data["detail"]
        == "The change has been applied: every arrangement was accommodated."
    )
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.APPLIED
    booking, reservation, event = arrangements(gala)
    assert booking == (BookingStatus.APPROVED, START + NEXT_DAY, END + NEXT_DAY, 120)
    assert reservation == (START + NEXT_DAY, END + NEXT_DAY, 3)
    assert event == (START + NEXT_DAY, END + NEXT_DAY, 120)


@pytest.mark.django_db
def test_s4_80_02_ac2_before_and_after_history_is_kept(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    fields = dict(
        EventFieldChange.objects.filter(event=gala, source=ChangeSource.CHANGE_REQUEST).values_list(
            "field", "after"
        )
    )
    assert at(fields["preferred_start"]) == START + NEXT_DAY
    booking_note = VenueBookingHistory.objects.filter(booking__event=gala).latest("pk")
    assert booking_note.actor == venue_staff
    assert booking_note.reason.startswith(f"Approved change request {change.pk} applied. Period ")
    amended = EquipmentHistory.objects.filter(
        plan__event=gala, action=EquipmentHistoryAction.AMENDED
    ).get()
    assert (amended.actor, at(amended.before["starts_at"])) == (tech, START)


@pytest.mark.django_db
def test_s4_80_02_an_attendance_change_revises_the_main_booking(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = approved_change(gala, organiser, coordinator, expected_attendance=140)
    coordinator_api.post(apply_url(change))
    assert kinds(change) == ["VENUE"]

    outcome_of(api, venue_staff, change.arrangement_reviews.get())

    booking, _, event = arrangements(gala)
    assert (booking[3], event[2]) == (140, 140)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("outcome", "reason", "field", "message"),
    [
        ("MAYBE", "Fine.", "outcome", "Choose whether the change can be accommodated."),
        (None, "Fine.", "outcome", "Choose whether the change can be accommodated."),
        ("ACCOMMODATED", "  ", "reason", "Enter the reason for your outcome."),
        ("ACCOMMODATED", None, "reason", "Enter the reason for your outcome."),
    ],
)
def test_s4_80_02_an_outcome_needs_a_choice_and_a_reason(
    api, coordinator_api, organiser, coordinator, venue_staff, gala, outcome, reason, field, message
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))

    response = outcome_of(
        api, venue_staff, change.arrangement_reviews.get(kind="VENUE"), outcome, reason
    )

    assert response.status_code == 400
    assert response.data[field] == [message]


@pytest.mark.django_db
def test_s4_80_02_staff_review_only_their_own_kind(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))

    wrong = outcome_of(api, tech, change.arrangement_reviews.get(kind="VENUE"))
    other = outcome_of(api, coordinator, change.arrangement_reviews.get(kind="VENUE"))

    assert wrong.status_code == 403
    assert AuditLog.objects.filter(actor=tech, allowed=False).exists()
    assert other.status_code == 403


@pytest.mark.django_db
def test_s4_80_02_an_outcome_cannot_be_recorded_twice(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    review = change.arrangement_reviews.get(kind="VENUE")
    outcome_of(api, venue_staff, review)

    again = outcome_of(api, venue_staff, review, "NOT_ACCOMMODATED", "Changed my mind.")

    assert again.status_code == 409
    assert again.data["detail"] == "This arrangement is already can be accommodated."


@pytest.mark.django_db
def test_s4_80_02_an_accommodation_is_rechecked_against_current_bookings(
    api, coordinator_api, organiser, coordinator, venue_staff, venue, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    # After the preview, another event's booking takes the new date.
    other = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Board Day",
        expected_attendance=100,
    )
    approved_booking(
        other, venue, coordinator, venue_staff, start=START + NEXT_DAY, end=END + NEXT_DAY
    )
    review = change.arrangement_reviews.get(kind="VENUE")

    response = outcome_of(api, venue_staff, review)

    assert response.status_code == 409
    assert response.data["problems"] == ["Harbour Hall is already booked at the proposed time."]
    review.refresh_from_db()
    assert review.outcome == ArrangementOutcome.PENDING


@pytest.mark.django_db
def test_s4_80_02_equipment_is_rechecked_against_current_stock(
    api, coordinator_api, organiser, coordinator, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    EquipmentType.objects.filter(code="PROJECTOR").update(total_quantity=2)

    response = outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert response.status_code == 409
    assert response.data["problems"] == [
        "Only 2 Projector available at the proposed time; 3 reserved."
    ]


@pytest.mark.django_db
def test_s4_80_02_a_failed_switch_notice_rolls_everything_back(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    before = arrangements(gala)
    review = change.arrangement_reviews.get(kind="EQUIPMENT")

    with (
        mock.patch(
            "apps.events.impact.notify_attendees_of_change", side_effect=RuntimeError("down")
        ),
        pytest.raises(RuntimeError),
    ):
        review_arrangement(review=review, actor=tech, outcome="ACCOMMODATED", reason="OK.")

    assert arrangements(gala) == before
    review.refresh_from_db()
    change.refresh_from_db()
    assert (review.outcome, change.status) == (
        ArrangementOutcome.PENDING,
        ChangeRequestStatus.IN_REVIEW,
    )


# S4-80-03 - AC3: staff cannot accommodate; the original stays until agreed.


@pytest.mark.django_db
def test_s4_80_03_ac3_cannot_accommodate_keeps_the_original_and_tells_people(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    before = arrangements(gala)

    response = outcome_of(
        api,
        venue_staff,
        change.arrangement_reviews.get(kind="VENUE"),
        "NOT_ACCOMMODATED",
        "The hall is closed for maintenance that day.",
    )

    assert response.status_code == 200
    assert arrangements(gala) == before
    notices = Notification.objects.filter(kind=NotificationKind.CHANGE_OUTCOME)
    assert {n.recipient_id for n in notices} == {coordinator.pk, organiser.pk}
    assert (
        "The current arrangement stays in place until you agree the next step."
        in notices.first().message
    )
    assert (
        f"Change: staff cannot accommodate approved change request #{change.pk}; "
        "agree the next step with the organiser."
    ) in arrangement_gaps(gala)


@pytest.mark.django_db
def test_s4_80_03_ac3_the_coordinator_records_that_the_original_is_kept(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(
        api,
        venue_staff,
        change.arrangement_reviews.get(kind="VENUE"),
        "NOT_ACCOMMODATED",
        "Closed.",
    )
    before = arrangements(gala)
    url = f"/api/change-requests/{change.pk}/keep-original/"

    missing = coordinator_api.post(url, {"reason": " "}, format="json")
    kept = coordinator_api.post(
        url, {"reason": "Organiser agreed to keep the original date."}, format="json"
    )

    assert missing.status_code == 400
    assert missing.data["reason"] == ["Enter what was agreed with the organiser."]
    assert kept.status_code == 200
    change.refresh_from_db()
    assert (change.status, change.completion_note) == (
        ChangeRequestStatus.ORIGINAL_KEPT,
        "Organiser agreed to keep the original date.",
    )
    assert arrangements(gala) == before
    gaps = arrangement_gaps(gala)
    assert not any(gap.startswith("Change:") for gap in gaps)
    assert not any("needs staff review of the proposed period" in gap for gap in gaps)
    assert Notification.objects.filter(
        kind=NotificationKind.CHANGE_OUTCOME,
        recipient=organiser,
        occurrence=f"CHANGE_OUTCOME:change-original-kept:{change.pk}",
    ).exists()


@pytest.mark.django_db
def test_s4_80_03_the_original_is_kept_only_after_a_refusal(
    coordinator_api, organiser, coordinator, gala
):
    change = move_one_day(gala, organiser, coordinator)
    url = f"/api/change-requests/{change.pk}/keep-original/"

    not_applied = coordinator_api.post(url, {"reason": "Agreed."}, format="json")
    coordinator_api.post(apply_url(change))
    no_refusal = coordinator_api.post(url, {"reason": "Agreed."}, format="json")

    assert not_applied.status_code == 409
    assert no_refusal.status_code == 409
    assert no_refusal.data["detail"].startswith("The original can be kept only after staff record")


@pytest.mark.django_db
def test_s4_80_03_only_the_assigned_coordinator_keeps_the_original(
    api, coordinator_api, organiser, coordinator, second_coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(
        api, venue_staff, change.arrangement_reviews.get(kind="VENUE"), "NOT_ACCOMMODATED", "No."
    )
    type(gala).objects.filter(pk=gala.pk).update(coordinator=second_coordinator)
    api.force_authenticate(coordinator)

    response = api.post(
        f"/api/change-requests/{change.pk}/keep-original/", {"reason": "Agreed."}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_s4_80_03_no_more_outcomes_once_the_original_is_kept(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(
        api, venue_staff, change.arrangement_reviews.get(kind="VENUE"), "NOT_ACCOMMODATED", "No."
    )
    coordinator_api.post(
        f"/api/change-requests/{change.pk}/keep-original/", {"reason": "Agreed."}, format="json"
    )

    late = outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert late.status_code == 409
    assert late.data["detail"] == "This change is no longer waiting for staff review."


# S4-80-04 - AC4: the organiser, affected staff and registered attendees are notified.


@pytest.mark.django_db
def test_s4_80_04_ac4_applied_change_reaches_organiser_staff_and_attendees(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    outcome = Notification.objects.filter(kind=NotificationKind.CHANGE_OUTCOME)
    assert {organiser.pk, coordinator.pk, venue_staff.pk} <= set(
        outcome.values_list("recipient_id", flat=True)
    )
    # Technical Support recorded the last outcome themselves, so they are not re-told.
    assert not outcome.filter(recipient=tech).exists()
    attendees = Notification.objects.filter(kind=NotificationKind.EVENT_CHANGED)
    assert sorted(attendees.values_list("recipient__email", flat=True)) == [
        "amy@example.com",
        "ben@example.com",
    ]
    assert attendees.first().message.startswith(
        'The date of "Annual Gala", which you are registered for'
    )


@pytest.mark.django_db
def test_s4_80_04_a_time_only_change_is_described_as_the_time(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = approved_change(
        gala,
        organiser,
        coordinator,
        preferred_start=START.replace(hour=13),
        preferred_end=END.replace(hour=15),
    )
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    notice = Notification.objects.filter(kind=NotificationKind.EVENT_CHANGED).first()
    assert notice.message.startswith('The time of "Annual Gala"')


@pytest.mark.django_db
def test_s4_80_04_an_attendance_change_does_not_notify_attendees(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = approved_change(gala, organiser, coordinator, expected_attendance=140)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get())

    assert not Notification.objects.filter(kind=NotificationKind.EVENT_CHANGED).exists()


# S4-80-05 - AC5: the history shows the request, decision, outcomes and who.


@pytest.mark.django_db
def test_s4_80_05_ac5_the_history_shows_request_decision_outcomes_and_staff(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"), reason="Stock is fine.")

    api.force_authenticate(organiser)
    data = api.get(f"/api/change-requests/{change.pk}/history/").data

    assert (data["status"], data["requested_by"]) == (ChangeRequestStatus.APPLIED, "Ada Organiser")
    assert (data["decision"]["decided_by"], data["decision"]["reason"]) == (
        "Cora Coordinator",
        "Agreed.",
    )
    assert data["applied_by"] == "Cora Coordinator"
    outcomes = {
        (a["kind"], a["outcome"], a["reviewed_by"], a["review_reason"])
        for a in data["arrangements"]
    }
    assert outcomes == {
        ("VENUE", "ACCOMMODATED", "Vera Venue", "We can do the new date."),
        ("EQUIPMENT", "ACCOMMODATED", "tech@example.com", "Stock is fine."),
    }
    assert {f["field"] for f in data["field_changes"]} == {"preferred_start", "preferred_end"}


@pytest.mark.django_db
def test_s4_80_05_the_history_is_kept_from_attendees_and_other_organisations(
    api, organiser, coordinator, other_organiser, attendee, gala
):
    change = move_one_day(gala, organiser, coordinator)
    for user in (other_organiser, attendee):
        api.force_authenticate(user)
        assert api.get(f"/api/change-requests/{change.pk}/history/").status_code == 403


# S4-80-06 - AC6: Safety superseded, back to Planning, only affected items re-approved.


@pytest.mark.django_db
def test_s4_80_06_ac6_applying_supersedes_safety_and_returns_to_planning(
    coordinator_api, organiser, coordinator, gala
):
    check = make_check(gala)
    change = move_one_day(gala, organiser, coordinator)

    coordinator_api.post(apply_url(change))

    check.refresh_from_db()
    gala.refresh_from_db()
    assert (check.status, gala.status) == (SafetyStatus.SUPERSEDED, EventStatus.PLANNING)
    assert (
        f"Change: approved change request #{change.pk} is awaiting staff review."
        in arrangement_gaps(gala)
    )


@pytest.mark.django_db
def test_s4_80_06_ac6_only_the_affected_equipment_goes_back_through_approval(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert (
        TechnicalApproval.objects.filter(
            plan__event=gala, status=TechnicalApprovalStatus.APPROVED
        ).count()
        == 0
    )
    gaps = arrangement_gaps(gala)
    assert "Technical: the equipment plan has not been approved by Technical Support." in gaps
    # The venue was accommodated and stays approved - it is not a gap.
    assert not any(gap.startswith("Venue:") for gap in gaps)


@pytest.mark.django_db
def test_s4_80_06_an_equipment_only_change_leaves_the_venue_alone(
    api, coordinator_api, organiser, coordinator, tech, gala
):
    booking_before = arrangements(gala)[0]
    change = approved_change(
        gala, organiser, coordinator, equipment_notes="Add two lapel microphones."
    )

    coordinator_api.post(apply_url(change))
    assert kinds(change) == ["EQUIPMENT"]
    outcome_of(api, tech, change.arrangement_reviews.get(), reason="Microphones available.")

    change.refresh_from_db()
    gala.refresh_from_db()
    assert change.status == ChangeRequestStatus.APPLIED
    assert gala.equipment_notes == "Add two lapel microphones."
    assert arrangements(gala)[0] == booking_before


@pytest.mark.django_db
def test_s4_80_06_the_service_refuses_an_unapproved_change_too(organiser, coordinator, gala):
    change = change_for(gala, organiser, expected_attendance=140)

    with pytest.raises(ApplyRefused):
        apply_change(change=change, actor=coordinator)


# S4-80-07 - edge cases: refusals found under the locks, and late changes.


def other_booking_next_day(organiser, coordinator, venue_staff, venue):
    other = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Board Day",
        expected_attendance=100,
    )
    return approved_booking(
        other, venue, coordinator, venue_staff, start=START + NEXT_DAY, end=END + NEXT_DAY
    )


@pytest.mark.django_db
def test_s4_80_07_a_clash_already_at_the_proposed_time_is_listed_for_review(
    coordinator_api, organiser, coordinator, venue_staff, venue, gala
):
    other_booking_next_day(organiser, coordinator, venue_staff, venue)
    change = move_one_day(gala, organiser, coordinator)

    coordinator_api.post(apply_url(change))

    review = change.arrangement_reviews.get(kind="VENUE")
    assert "Another booking already holds the venue at the proposed time." in review.reasons


@pytest.mark.django_db
def test_s4_80_07_the_services_refuse_a_reassigned_coordinator(
    organiser, coordinator, second_coordinator, venue_staff, gala
):
    from apps.events.change_requests import NotAssignedCoordinator
    from apps.events.impact import keep_original

    change = move_one_day(gala, organiser, coordinator)
    type(gala).objects.filter(pk=gala.pk).update(coordinator=second_coordinator)

    with pytest.raises(NotAssignedCoordinator):
        apply_change(change=change, actor=coordinator)
    with pytest.raises(NotAssignedCoordinator):
        keep_original(change=change, actor=coordinator, reason="Agreed.")


@pytest.mark.django_db
def test_s4_80_07_a_refusal_found_under_the_lock_when_keeping_is_audited(
    coordinator_api, organiser, coordinator, gala
):
    from apps.events.change_requests import NotAssignedCoordinator

    change = move_one_day(gala, organiser, coordinator)
    with mock.patch("apps.events.change_views.keep_original", side_effect=NotAssignedCoordinator):
        response = coordinator_api.post(
            f"/api/change-requests/{change.pk}/keep-original/", {"reason": "Agreed."}, format="json"
        )

    assert response.status_code == 403
    assert AuditLog.objects.filter(
        actor=coordinator, allowed=False, detail="only the assigned coordinator may close a change"
    ).exists()


@pytest.mark.django_db
def test_s4_80_07_a_booking_withdrawn_during_review_cannot_be_accommodated(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    VenueBooking.objects.filter(event=gala).update(status=BookingStatus.WITHDRAWN)

    response = outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))

    assert response.status_code == 409
    assert response.data["problems"] == [
        "The booking for Harbour Hall is no longer approved or held."
    ]


@pytest.mark.django_db
def test_s4_80_07_a_venue_the_change_makes_unsuitable_cannot_be_accommodated(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = approved_change(gala, organiser, coordinator, expected_attendance=151)
    coordinator_api.post(apply_url(change))

    response = outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))

    assert response.status_code == 409
    assert any("151" in problem for problem in response.data["problems"])


@pytest.mark.django_db
def test_s4_80_07_equipment_that_cannot_be_accommodated_tells_the_coordinator(
    api, coordinator_api, organiser, coordinator, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))

    outcome_of(
        api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"), "NOT_ACCOMMODATED", "No stock."
    )

    notice = Notification.objects.get(kind=NotificationKind.CHANGE_OUTCOME, recipient=coordinator)
    assert "for Projector: No stock." in notice.message


@pytest.mark.django_db
def test_s4_80_07_an_event_changed_during_review_is_not_switched(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    type(gala).objects.filter(pk=gala.pk).update(description="Edited during review")
    before = arrangements(gala)

    response = outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert response.status_code == 409
    assert response.data["detail"].startswith(
        "The event has changed since this change was approved"
    )
    assert arrangements(gala) == before


@pytest.mark.django_db
def test_s4_80_07_the_switch_rechecks_every_accommodated_arrangement(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, venue, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    # After Venue Staff accommodated it, another booking takes the new date.
    other_booking_next_day(organiser, coordinator, venue_staff, venue)
    before = arrangements(gala)

    response = outcome_of(api, tech, change.arrangement_reviews.get(kind="EQUIPMENT"))

    assert response.status_code == 409
    assert response.data["problems"] == ["Harbour Hall is already booked at the proposed time."]
    assert arrangements(gala) == before
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.IN_REVIEW


@pytest.mark.django_db
def test_s4_80_07_a_cancelled_event_leaves_no_live_review_work(
    api, coordinator_api, organiser, coordinator, venue_staff, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    type(gala).objects.filter(pk=gala.pk).update(status=EventStatus.CANCELLED)
    api.force_authenticate(venue_staff)

    assert api.get("/api/arrangement-reviews/").data == []
    response = outcome_of(api, venue_staff, change.arrangement_reviews.get(kind="VENUE"))
    assert response.status_code == 409
    assert response.data["detail"] == "A Cancelled event takes no further changes."


@pytest.mark.django_db
def test_s4_80_07_a_closed_change_leaves_no_live_review_work(
    api, coordinator_api, organiser, coordinator, venue_staff, tech, gala
):
    change = move_one_day(gala, organiser, coordinator)
    coordinator_api.post(apply_url(change))
    outcome_of(
        api, venue_staff, change.arrangement_reviews.get(kind="VENUE"), "NOT_ACCOMMODATED", "No."
    )
    coordinator_api.post(
        f"/api/change-requests/{change.pk}/keep-original/", {"reason": "Agreed."}, format="json"
    )
    api.force_authenticate(tech)

    # The equipment review was never recorded, but its change is closed.
    assert api.get("/api/arrangement-reviews/").data == []
