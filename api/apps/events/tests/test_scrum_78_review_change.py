"""SCRUM-78 - Review a change request and assess its impact (Sprint 4 gate ASSESS).

As an Event Coordinator, I want to see which existing arrangements a requested
change would affect, so that I can decide on it with full knowledge rather than
discovering the consequences afterwards.

The arrangements are made through the real actions: a venue booking requested
and approved by Venue Staff, an equipment request, attendee registrations and
the organiser's change request. Two low-level fixtures are labelled where used:
the event's Confirmed status (real confirmation needs the whole Safety flow)
and another event's equipment reservation (stock pressure).

Case IDs follow the Sprint 4 guide: S4-78-<case>.
"""

import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentReservation, EquipmentType, ReservationStatus
from apps.equipment.services import create_request
from apps.events.change_requests import decide_change, request_change
from apps.events.impact import NO_IMPACT, assess_change
from apps.events.models import (
    ChangeRequestStatus,
    EventChangeRequest,
    EventFieldChange,
    VenuePeriodReview,
    VenueReview,
)
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import RegistrationPolicy
from apps.registrations.services import register
from apps.venues.bookings import approve_booking, create_booking_record
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime.datetime(2027, 3, 1, 10, 0, tzinfo=SGT)
END = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=SGT)
NEXT_DAY = datetime.timedelta(days=1)
WHY = "Our keynote speaker can only attend then."


def impact_url(change):
    return f"/api/change-requests/{change.pk}/impact/"


def decide_url(change):
    return f"/api/change-requests/{change.pk}/decide/"


def hall():
    """Capacity 150, Theatre, open 08:00-22:00 daily."""
    return make_venue(
        name="Harbour Hall",
        capacity=150,
        layouts=["THEATRE"],
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )


def approved_booking(event, venue, coordinator, venue_staff, *, start=START, end=END):
    """A booking requested by the coordinator and approved by Venue Staff (real actions)."""
    booking = create_booking_record(
        requested_by=coordinator,
        event=event,
        venue=venue,
        starts_at=start,
        ends_at=end,
        attendance=event.expected_attendance,
        layout="THEATRE",
    )
    return approve_booking(booking, venue_staff)


def planning_event(organiser, coordinator, venue_staff, venue, *, name="Annual Gala"):
    """A Planning event with an approved venue (real request and Venue Staff approval)."""
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name=name,
        preferred_start=START,
        preferred_end=END,
        expected_attendance=120,
        required_layout="THEATRE",
    )
    approved_booking(event, venue, coordinator, venue_staff)
    return event


def mark_confirmed(event):
    """Low-level fixture: real confirmation needs the whole Safety flow (SCRUM-58/90)."""
    type(event).objects.filter(pk=event.pk).update(status=EventStatus.CONFIRMED)
    event.refresh_from_db()


def open_registration(event, capacity=100):
    now = timezone.now()
    return RegistrationPolicy.objects.create(
        event=event,
        enabled=True,
        opens_at=now - datetime.timedelta(days=1),
        closes_at=now + datetime.timedelta(days=30),
        capacity=capacity,
    )


def attendee_named(email):
    return User.objects.create_user(username=email, email=email, role=Role.ATTENDEE)


@pytest.fixture
def venue(db):
    return hall()


@pytest.fixture
def projector(db):
    return EquipmentType.objects.create(code="PROJECTOR", name="Projector", total_quantity=10)


@pytest.fixture
def gala(organiser, coordinator, venue_staff, venue, projector):
    """Confirmed 'Annual Gala': approved Harbour Hall, 3 projectors requested, 2 registered."""
    event = planning_event(organiser, coordinator, venue_staff, venue)
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=3)
    mark_confirmed(event)
    open_registration(event)
    for email in ("amy@example.com", "ben@example.com"):
        register(event=event, attendee=attendee_named(email), full_name=email, email=email)
    event.refresh_from_db()
    return event


def change_for(event, organiser, *, description="Please change the event.", **proposed):
    return request_change(
        event=event,
        requested_by=organiser,
        description=description,
        reason=WHY,
        proposed_values={
            k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in proposed.items()
        },
    )


@pytest.fixture
def coordinator_api(api, coordinator):
    api.force_authenticate(coordinator)
    return api


def decided_notices():
    return Notification.objects.filter(kind=NotificationKind.CHANGE_DECIDED)


# S4-78-01 - AC1: a date/time or attendance change lists the arrangements it may affect.


@pytest.mark.django_db
def test_s4_78_01_ac1_a_date_change_lists_bookings_equipment_and_registrations(
    coordinator_api, organiser, gala
):
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    data = coordinator_api.get(impact_url(change)).data

    [booking] = data["venue_bookings"]
    assert (booking["venue"], booking["session"], booking["status"]) == (
        "Harbour Hall",
        "Main programme",
        BookingStatus.APPROVED,
    )
    assert booking["proposed_starts_at"] == START + NEXT_DAY
    assert booking["proposed_ends_at"] == END + NEXT_DAY
    [line] = data["equipment"]
    assert (line["equipment_type"], line["quantity"], line["available_at_proposed_time"]) == (
        "Projector",
        3,
        10,
    )
    assert line["shortfall"] == 0
    assert data["registrations"]["registered"] == 2
    assert data["registrations"]["affected"] is True
    assert data["registrations"]["reasons"] == [
        "2 registered attendee(s) signed up for the current date and time."
    ]
    assert (data["no_impact"], data["significant"]) == (False, True)


@pytest.mark.django_db
def test_s4_78_01_ac1_an_attendance_change_rechecks_the_booking(coordinator_api, organiser, gala):
    change = change_for(gala, organiser, expected_attendance=140)

    data = coordinator_api.get(impact_url(change)).data

    [booking] = data["venue_bookings"]
    assert booking["rechecked_for"] == ["expected_attendance"]
    assert booking["unsuitable"] is False
    # Attendance does not change the equipment period or the registrations.
    assert data["equipment"] == []
    assert data["registrations"]["affected"] is False


@pytest.mark.django_db
def test_s4_78_01_ac1_attendance_below_registrations_is_warned(organiser, gala):
    change = change_for(gala, organiser, expected_attendance=1)

    data = assess_change(change)

    assert data["registrations"]["reasons"] == [
        "The proposed attendance of 1 is below the 2 people already registered."
    ]


@pytest.mark.django_db
def test_s4_78_01_ac1_equipment_short_at_the_new_time_is_flagged(
    organiser, coordinator, venue_staff, gala, projector
):
    # Low-level fixture: another event already holds 8 of the 10 projectors next day.
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator, name="Expo")
    held = create_request(
        event=other, requested_by=coordinator, equipment_type=projector.pk, quantity=8
    )
    EquipmentReservation.objects.create(
        request=held,
        quantity=8,
        starts_at=START + NEXT_DAY,
        ends_at=END + NEXT_DAY,
        status=ReservationStatus.ACTIVE,
        reserved_by=venue_staff,
    )
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    data = assess_change(change)

    [line] = data["equipment"]
    assert (line["available_at_proposed_time"], line["shortfall"]) == (2, 1)
    assert (
        "Only 2 Projector available at the proposed time; 3 needed (1 short)." in data["warnings"]
    )


@pytest.mark.django_db
def test_s4_78_01_ac1_changed_equipment_needs_list_the_equipment(organiser, gala):
    change = change_for(gala, organiser, equipment_notes="Add two lapel microphones.")

    [line] = assess_change(change)["equipment"]

    assert line["reasons"] == ["The equipment requirements change."]
    assert line["available_at_proposed_time"] is None


@pytest.mark.django_db
def test_s4_78_01_a_live_hold_is_listed_and_checked_too(
    organiser, coordinator, venue_staff, projector
):
    venue = hall()
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=START,
        preferred_end=END,
        expected_attendance=100,
    )
    booking = create_booking_record(
        requested_by=coordinator,
        event=event,
        venue=venue,
        starts_at=START,
        ends_at=END,
        attendance=100,
    )
    # Low-level fixture: a live SCRUM-88 hold (the hold action is Venue Staff's).
    VenueBooking.objects.filter(pk=booking.pk).update(
        status=BookingStatus.HELD, hold_until=timezone.now() + datetime.timedelta(days=3)
    )
    change = change_for(
        event, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    [row] = assess_change(change)["venue_bookings"]

    assert (row["status"], row["proposed_starts_at"]) == (BookingStatus.HELD, START + NEXT_DAY)


# S4-78-02 - AC2: attendance beyond the booked venue's capacity flags it unsuitable.


@pytest.mark.django_db
def test_s4_78_02_ac2_attendance_above_capacity_flags_the_venue(coordinator_api, organiser, gala):
    change = change_for(gala, organiser, expected_attendance=151)

    data = coordinator_api.get(impact_url(change)).data

    [booking] = data["venue_bookings"]
    assert booking["unsuitable"] is True
    assert booking["unsuitable_reasons"]
    assert "151" in booking["unsuitable_reasons"][0]
    assert any(w.startswith("Harbour Hall may no longer suit the event:") for w in data["warnings"])


@pytest.mark.django_db
def test_s4_78_02_ac2_attendance_equal_to_capacity_is_suitable(organiser, gala):
    change = change_for(gala, organiser, expected_attendance=150)

    [booking] = assess_change(change)["venue_bookings"]

    assert booking["unsuitable"] is False


# S4-78-03 - AC3: a date change that clashes with another confirmed booking is identified.


@pytest.mark.django_db
def test_s4_78_03_ac3_a_clash_at_the_new_date_is_identified(
    coordinator_api, organiser, coordinator, venue_staff, venue, gala
):
    other = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Board Day",
        expected_attendance=100,
    )
    blocker = approved_booking(
        other, venue, coordinator, venue_staff, start=START + NEXT_DAY, end=END + NEXT_DAY
    )
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    data = coordinator_api.get(impact_url(change)).data

    [booking] = data["venue_bookings"]
    assert [(c["booking"], c["event"]) for c in booking["conflicts"]] == [(blocker.pk, other.pk)]
    assert (
        "Harbour Hall is already booked for another event at the proposed time." in data["warnings"]
    )


@pytest.mark.django_db
def test_s4_78_03_ac3_a_free_new_date_has_no_clash(organiser, gala):
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    [booking] = assess_change(change)["venue_bookings"]

    assert booking["conflicts"] == []


# S4-78-04 - AC4: no impact on existing arrangements is stated clearly.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "proposed",
    [{"name": "Annual Gala 2027"}, {"purpose": "Partner celebration"}, {}],
    ids=["name", "purpose", "description-only"],
)
def test_s4_78_04_ac4_no_impact_is_stated_clearly(coordinator_api, organiser, gala, proposed):
    change = change_for(gala, organiser, **proposed)

    data = coordinator_api.get(impact_url(change)).data

    assert data["no_impact"] is True
    assert data["summary"] == NO_IMPACT == "This change does not affect any existing arrangements."
    assert (data["venue_bookings"], data["equipment"], data["warnings"]) == ([], [], [])


@pytest.mark.django_db
def test_s4_78_04_an_event_without_arrangements_has_no_impact(
    coordinator_api, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    change = change_for(event, organiser, expected_attendance=200)

    data = coordinator_api.get(impact_url(change)).data

    assert data["no_impact"] is True
    assert data["significant"] is True


@pytest.mark.django_db
def test_s4_78_04_the_assessment_writes_nothing(coordinator_api, organiser, gala):
    change = change_for(
        gala,
        organiser,
        preferred_start=START + NEXT_DAY,
        preferred_end=END + NEXT_DAY,
        expected_attendance=151,
    )
    before = (
        Notification.objects.count(),
        VenueReview.objects.count(),
        VenuePeriodReview.objects.count(),
        EquipmentReservation.objects.count(),
        list(VenueBooking.objects.values_list("pk", "status", "starts_at", "ends_at")),
    )

    coordinator_api.get(impact_url(change))
    coordinator_api.get(impact_url(change))

    after = (
        Notification.objects.count(),
        VenueReview.objects.count(),
        VenuePeriodReview.objects.count(),
        EquipmentReservation.objects.count(),
        list(VenueBooking.objects.values_list("pk", "status", "starts_at", "ends_at")),
    )
    assert after == before


@pytest.mark.django_db
def test_s4_78_04_a_stale_request_is_marked(coordinator_api, organiser, gala):
    change = change_for(gala, organiser, expected_attendance=140)
    type(gala).objects.filter(pk=gala.pk).update(description="Edited since")

    assert coordinator_api.get(impact_url(change)).data["stale"] is True


@pytest.mark.django_db
def test_s4_78_04_a_withdrawn_target_falls_back_to_every_booking(organiser, gala):
    booking = VenueBooking.objects.get(event=gala)
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )
    EventChangeRequest.objects.filter(pk=change.pk).update(target_bookings=[booking.pk + 999])
    change.refresh_from_db()

    data = assess_change(change)

    assert "A venue booking named in the request is no longer approved." in data["warnings"]
    assert [row["booking"] for row in data["venue_bookings"]] == [booking.pk]


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["organiser", "second_coordinator", "venue_staff", "attendee"])
def test_s4_78_04_only_the_coordinator_and_leads_open_the_assessment(
    api, organiser, gala, request, who
):
    change = change_for(gala, organiser, expected_attendance=140)
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.get(impact_url(change)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s4_78_04_a_lead_can_read_the_assessment(api, organiser, lead, gala):
    change = change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(lead)

    assert api.get(impact_url(change)).status_code == 200


# S4-78-05 - AC5: approve or reject with a reason; the organiser is notified.


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("decision", "status", "verb"),
    [
        ("APPROVE", ChangeRequestStatus.APPROVED, "approved"),
        ("REJECT", ChangeRequestStatus.REJECTED, "rejected"),
    ],
)
def test_s4_78_05_ac5_the_decision_and_reason_are_recorded(
    coordinator_api, organiser, coordinator, gala, decision, status, verb
):
    change = change_for(gala, organiser, expected_attendance=140)
    before = timezone.now()

    response = coordinator_api.post(
        decide_url(change),
        {"decision": decision, "reason": "  Agreed with the venue.  "},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["detail"] == f"Change request {verb}. The organiser has been notified."
    change.refresh_from_db()
    assert (change.status, change.decided_by, change.decision_reason) == (
        status,
        coordinator,
        "Agreed with the venue.",
    )
    assert before <= change.decided_at <= timezone.now()


@pytest.mark.django_db
def test_s4_78_05_ac5_the_organiser_is_notified_once(coordinator_api, organiser, gala):
    change = change_for(gala, organiser, expected_attendance=140)

    coordinator_api.post(
        decide_url(change), {"decision": "REJECT", "reason": "No room."}, format="json"
    )

    [notice] = decided_notices()
    assert (notice.recipient, notice.event) == (organiser, gala)
    assert notice.occurrence == f"CHANGE_DECIDED:change-decision:{change.pk}"
    assert notice.message == 'Your change request for "Annual Gala" was rejected. Reason: No room.'


@pytest.mark.django_db
def test_s4_78_05_ac5_scrum_20_the_organiser_sees_the_real_decision(
    api, organiser, coordinator, gala
):
    change = change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(coordinator)
    api.post(decide_url(change), {"decision": "APPROVE", "reason": "Room fits."}, format="json")

    api.force_authenticate(organiser)
    [row] = api.get(f"/api/events/{gala.pk}/change-requests/").data

    assert (row["status_label"], row["decided_by_name"], row["decision_reason"]) == (
        "Approved",
        "Cora Coordinator",
        "Room fits.",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_s4_78_05_ac5_a_reason_is_required(coordinator_api, organiser, gala, reason):
    change = change_for(gala, organiser, expected_attendance=140)

    response = coordinator_api.post(
        decide_url(change), {"decision": "APPROVE", "reason": reason}, format="json"
    )

    assert response.status_code == 400
    assert response.data["reason"] == ["Enter the reason for your decision."]
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.PENDING
    assert not decided_notices().exists()


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["MAYBE", "", None, True, "approve"])
def test_s4_78_05_the_decision_must_be_approve_or_reject(
    coordinator_api, organiser, gala, decision
):
    change = change_for(gala, organiser, expected_attendance=140)

    response = coordinator_api.post(
        decide_url(change), {"decision": decision, "reason": "Fine."}, format="json"
    )

    assert response.status_code == 400
    assert response.data["decision"] == ["Choose whether to approve or reject the change."]


@pytest.mark.django_db
def test_s4_78_05_the_decision_moves_no_arrangement(coordinator_api, organiser, gala):
    change = change_for(
        gala,
        organiser,
        preferred_start=START + NEXT_DAY,
        preferred_end=END + NEXT_DAY,
        expected_attendance=140,
    )
    arrangements = lambda: (  # noqa: E731
        list(VenueBooking.objects.values_list("pk", "status", "starts_at", "ends_at")),
        list(EquipmentReservation.objects.values_list("pk", "status", "quantity")),
        gala.registrations.filter(status="REGISTERED").count(),
        type(gala)
        .objects.values_list("preferred_start", "expected_attendance", "status")
        .get(pk=gala.pk),
    )
    before = arrangements()

    coordinator_api.post(
        decide_url(change), {"decision": "APPROVE", "reason": "OK."}, format="json"
    )

    assert arrangements() == before
    assert not EventFieldChange.objects.filter(event=gala).exists()


@pytest.mark.django_db
def test_s4_78_05_a_decided_request_cannot_be_decided_again(coordinator_api, organiser, gala):
    change = change_for(gala, organiser, expected_attendance=140)
    coordinator_api.post(decide_url(change), {"decision": "REJECT", "reason": "No."}, format="json")

    response = coordinator_api.post(
        decide_url(change), {"decision": "APPROVE", "reason": "Changed my mind."}, format="json"
    )

    assert response.status_code == 409
    assert response.data["detail"] == "This change request is already Rejected."
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.REJECTED
    assert decided_notices().count() == 1


@pytest.mark.django_db
def test_s4_78_05_a_stale_request_cannot_be_approved_but_can_be_rejected(
    coordinator_api, organiser, gala
):
    change = change_for(gala, organiser, expected_attendance=140)
    type(gala).objects.filter(pk=gala.pk).update(description="Edited since")

    refused = coordinator_api.post(
        decide_url(change), {"decision": "APPROVE", "reason": "OK."}, format="json"
    )
    rejected = coordinator_api.post(
        decide_url(change),
        {"decision": "REJECT", "reason": "Please send a new request."},
        format="json",
    )

    assert refused.status_code == 409
    assert refused.data["detail"].startswith("The event has changed since this was requested")
    assert refused.data["assessment"]["stale"] is True
    assert rejected.status_code == 200
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.REJECTED


@pytest.mark.django_db
@pytest.mark.parametrize("event_status", [EventStatus.CANCELLED, EventStatus.COMPLETED])
def test_s4_78_05_a_finished_event_cannot_take_an_approved_change(
    coordinator_api, organiser, gala, event_status
):
    change = change_for(gala, organiser, expected_attendance=140)
    type(gala).objects.filter(pk=gala.pk).update(status=event_status)

    response = coordinator_api.post(
        decide_url(change), {"decision": "APPROVE", "reason": "OK."}, format="json"
    )

    assert response.status_code == 400
    assert response.data["event"] == [
        f"A {EventStatus(event_status).label} event cannot take an approved change."
    ]


@pytest.mark.django_db
def test_s4_78_05_another_coordinator_cannot_decide(api, organiser, second_coordinator, gala):
    change = change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(second_coordinator)

    response = api.post(decide_url(change), {"decision": "APPROVE", "reason": "OK."}, format="json")

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=second_coordinator, allowed=False).exists()
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.PENDING


@pytest.mark.django_db
def test_s4_78_05_the_service_refuses_a_reassigned_coordinator(
    organiser, coordinator, second_coordinator, gala
):
    from apps.events.change_requests import NotAssignedCoordinator

    change = change_for(gala, organiser, expected_attendance=140)
    type(gala).objects.filter(pk=gala.pk).update(coordinator=second_coordinator)

    with pytest.raises(NotAssignedCoordinator):
        decide_change(change=change, actor=coordinator, decision="APPROVE", reason="OK.")


@pytest.mark.django_db
def test_s4_78_05_a_refusal_found_under_the_lock_is_audited(
    coordinator_api, coordinator, organiser, gala
):
    from apps.events.change_requests import NotAssignedCoordinator

    change = change_for(gala, organiser, expected_attendance=140)
    with mock.patch("apps.events.change_views.decide_change", side_effect=NotAssignedCoordinator):
        response = coordinator_api.post(
            decide_url(change), {"decision": "APPROVE", "reason": "OK."}, format="json"
        )

    assert response.status_code == 403
    assert AuditLog.objects.filter(
        actor=coordinator,
        allowed=False,
        detail="only the assigned coordinator may decide a change request",
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["lead", "organiser", "venue_staff"])
def test_s4_78_05_only_coordinators_decide(api, organiser, gala, request, who):
    change = change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(request.getfixturevalue(who))

    assert (
        api.post(
            decide_url(change), {"decision": "REJECT", "reason": "No."}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_s4_78_05_a_failed_notice_rolls_the_decision_back(organiser, coordinator, gala):
    change = change_for(gala, organiser, expected_attendance=140)

    with (
        mock.patch("apps.notifications.services.notify", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        decide_change(change=change, actor=coordinator, decision="APPROVE", reason="OK.")

    change.refresh_from_db()
    assert (change.status, change.decided_at) == (ChangeRequestStatus.PENDING, None)


@pytest.mark.django_db
def test_s4_78_05_an_unknown_change_request_is_not_found(coordinator_api):
    assert coordinator_api.get("/api/change-requests/999999/impact/").status_code == 404


@pytest.mark.django_db
def test_s4_78_01_a_request_naming_equipment_lists_it(organiser, gala):
    line = gala.equipment_plan.requests.get()
    change = request_change(
        event=gala,
        requested_by=organiser,
        description="Swap the projectors for screens.",
        reason=WHY,
        target_equipment_requests=[line.pk],
    )

    [row] = assess_change(change)["equipment"]

    assert (row["request"], row["reasons"]) == (line.pk, ["The request names this equipment."])


@pytest.mark.django_db
def test_s4_78_04_an_event_already_at_the_proposed_time_has_nothing_to_move(organiser, gala):
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )
    type(gala).objects.filter(pk=gala.pk).update(
        preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )
    gala.refresh_from_db()

    data = assess_change(change, event=gala)

    assert data["venue_bookings"] == []
    assert data["equipment"] == []
    assert data["stale"] is True


@pytest.mark.django_db
def test_s4_78_04_an_event_without_dates_has_no_period_to_check(organiser, coordinator):
    from apps.events.impact import _period_change

    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    event.preferred_start = event.preferred_end = None

    assert _period_change(event, {"preferred_start": START}) is None
