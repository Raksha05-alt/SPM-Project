"""SCRUM-90 (Week 7 change 6) - Safety Officer performs an Operational Safety Check.

Gate G20 workflow tests, through the real API. Each test is named after the
acceptance criterion it verifies. The shared readiness, version and
invalidation rules are covered by test_scrum_90_safety_contract.py (G04).
Case IDs match docs/test-cases/S3-SCRUM-90-safety.csv.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentPlan, EquipmentReservation
from apps.events.services import NotAssignedCoordinator, transition_event
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import (
    ConfirmationBlocked,
    NotSafetyOfficer,
    SafetyRefused,
    arrangements_changed,
    decide,
    request_check,
)
from apps.venues.bookings import create_booking_record, transition_booking
from apps.venues.models import BookingStatus
from conftest import _make_user, make_event

from .conftest import approve_equipment, approve_venue, make_venue


def request_url(event):
    return f"/api/events/{event.pk}/safety-checks/"


def detail_url(check):
    return f"/api/safety-checks/{check.pk}/"


def decide_url(check):
    return f"/api/safety-checks/{check.pk}/decide/"


def refusals(fragment):
    return AuditLog.objects.filter(allowed=False, action__contains=fragment)


@pytest.fixture
def pending_check(ready_event, coordinator, safety_officer):
    return request_check(ready_event, coordinator, "Please check the stage area.")


@pytest.fixture
def approved_check(pending_check, safety_officer):
    return decide(pending_check, safety_officer, SafetyStatus.APPROVED)


# --------------------------------------------------------------------------
# AC1 - request a check once the venue and technical arrangements are approved
# --------------------------------------------------------------------------


def test_ac1a_assigned_coordinator_requests_a_check_and_safety_officers_are_notified(
    api, ready_event, coordinator, safety_officer, second_safety_officer
):
    api.force_authenticate(coordinator)

    response = api.post(request_url(ready_event), {"note": "Pyrotechnics removed."})

    assert response.status_code == 201
    assert response.data["status"] == SafetyStatus.PENDING
    assert response.data["requested_by_name"] == "Cora Coordinator"
    check = SafetyCheck.objects.get(event=ready_event)
    assert check.request_note == "Pyrotechnics removed."
    assert check.requested_by == coordinator
    notified = Notification.objects.filter(kind=NotificationKind.SAFETY_REQUESTED)
    assert {n.recipient for n in notified} == {safety_officer, second_safety_officer}
    assert all(ready_event.name in n.message for n in notified)
    assert AuditLog.objects.filter(
        allowed=True, action=f"Safety check requested for event {ready_event.pk}"
    ).exists()


def test_ac1b_before_venue_approval_the_request_is_refused_and_gaps_listed(
    api, planning_event, coordinator, venue, tech
):
    approve_equipment(planning_event, tech)
    create_booking_record(
        requested_by=coordinator,
        event=planning_event,
        venue=venue,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=100,
    )
    api.force_authenticate(coordinator)

    response = api.post(request_url(planning_event), {})

    assert response.status_code == 409
    assert response.data["arrangement_gaps"] == [
        "Venue: no venue booking has been approved by Venue Staff.",
        "Venue: the booking request for Harbour Hall is still awaiting Venue Staff.",
    ]
    assert not SafetyCheck.objects.exists()
    assert not Notification.objects.filter(kind=NotificationKind.SAFETY_REQUESTED).exists()
    assert refusals("safety-checks").get().actor == coordinator


def test_ac1c_before_technical_approval_the_request_is_refused_and_gaps_listed(
    api, planning_event, coordinator, venue, venue_staff
):
    approve_venue(planning_event, venue, venue_staff)
    api.force_authenticate(coordinator)

    response = api.post(request_url(planning_event), {})

    assert response.status_code == 409
    assert response.data["arrangement_gaps"] == [
        "Technical: the equipment plan has not been approved by Technical Support."
    ]
    assert not SafetyCheck.objects.exists()


@pytest.mark.parametrize(
    "status", [EventStatus.SUBMITTED, EventStatus.APPROVED, EventStatus.CONFIRMED]
)
def test_ac1d_a_check_is_requested_only_while_the_event_is_in_planning(
    api, ready_event, coordinator, status
):
    ready_event.status = status
    ready_event.save(update_fields=["status"])
    api.force_authenticate(coordinator)

    response = api.post(request_url(ready_event), {})

    assert response.status_code == 409
    assert "Planning" in response.data["detail"]
    assert not SafetyCheck.objects.exists()


def test_ac1e_only_the_currently_assigned_coordinator_can_request(
    api, ready_event, second_coordinator, lead, safety_officer
):
    for user in (second_coordinator, lead, safety_officer):
        api.force_authenticate(user)
        assert api.post(request_url(ready_event), {}).status_code == 403
    assert not SafetyCheck.objects.exists()
    assert refusals(f"/api/events/{ready_event.pk}/safety-checks/").count() == 3


def test_ac1f_a_reassigned_coordinator_loses_the_request_action(
    ready_event, coordinator, second_coordinator
):
    """Ownership is reread under the event lock, not taken from a loaded page."""
    stale_copy = type(ready_event).objects.get(pk=ready_event.pk)
    ready_event.coordinator = second_coordinator
    ready_event.save(update_fields=["coordinator"])

    with pytest.raises(NotAssignedCoordinator):
        request_check(stale_copy, coordinator)


def test_ac1f_a_reassignment_during_the_request_is_refused_and_audited(
    api, ready_event, coordinator, monkeypatch
):
    def reassigned_meanwhile(event, actor, note=""):
        raise NotAssignedCoordinator

    monkeypatch.setattr("apps.safety.views.request_check", reassigned_meanwhile)
    api.force_authenticate(coordinator)

    assert api.post(request_url(ready_event), {}).status_code == 403
    assert refusals("safety-checks").get().detail == "no longer the coordinator"


def test_ac1g_one_standing_check_at_a_time(api, pending_check, coordinator):
    api.force_authenticate(coordinator)

    response = api.post(request_url(pending_check.event), {})

    assert response.status_code == 409
    assert "awaiting safety officer" in response.data["detail"]
    assert SafetyCheck.objects.count() == 1


def test_ac1h_the_event_view_shows_gaps_and_whether_a_check_can_be_requested(
    api, ready_event, coordinator, organiser
):
    api.force_authenticate(coordinator)
    data = api.get(request_url(ready_event)).data
    assert data["arrangement_gaps"] == []
    assert data["can_request"] is True
    assert data["checks"] == []

    unplanned = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    data = api.get(request_url(unplanned)).data
    assert data["can_request"] is False
    assert len(data["arrangement_gaps"]) == 2


# --------------------------------------------------------------------------
# AC2 - the Safety Officer sees what they need to review
# --------------------------------------------------------------------------


def test_ac2a_safety_officer_sees_attendance_venue_access_restrictions_and_equipment(
    api, pending_check, safety_officer
):
    api.force_authenticate(safety_officer)

    response = api.get(detail_url(pending_check))

    assert response.status_code == 200
    facts = response.data["current_facts"]
    assert facts == response.data["facts"]
    assert facts["expected_attendance"] == 120
    assert facts["accessibility_needs"] == "Two wheelchair users."
    [venue] = facts["venues"]
    assert venue["venue"] == "Harbour Hall"
    assert venue["capacity"] == 200
    assert venue["booked_attendance"] == 120
    assert venue["layout"] == "Theatre"
    assert venue["emergency_access"] == (
        "Two fire exits to the stairwell; assembly at the promenade."
    )
    assert venue["known_restrictions"] == "No open flames. Stage load limit 500 kg."
    assert venue["wheelchair_access"] is True
    assert facts["equipment"] == [
        {
            "equipment": "Projector",
            "quantity": 2,
            "reserved_quantity": 2,
            "status": "Reserved",
            "technical_requirements": "HDMI to both stage screens",
        }
    ]
    assert facts["technical_approval"]["approved_by"] == "Tariq Tech"
    assert facts["concerns"] == []


def test_ac2b_missing_or_worrying_recorded_facts_are_shown_explicitly(
    planning_event, coordinator, venue_staff, tech
):
    cramped = make_venue(
        "Garden Pavilion",
        capacity=80,
        wheelchair_access=False,
        emergency_access="",
        known_restrictions="",
    )
    approve_venue(planning_event, cramped, venue_staff, attendance=100)
    approve_equipment(planning_event, tech)

    check = request_check(planning_event, coordinator)

    assert check.facts["concerns"] == [
        "Garden Pavilion: 100 people booked for a capacity of 80.",
        "Garden Pavilion has no emergency access information recorded.",
        "Garden Pavilion has no known restrictions recorded.",
        "Garden Pavilion has no recorded wheelchair access, "
        "and the event has accessibility requirements.",
        "Expected attendance of 120 exceeds the combined venue capacity of 80.",
    ]
    assert check.status == SafetyStatus.PENDING  # concerns never decide for the officer


def test_ac2c_safety_officers_filter_the_queue_by_status(api, pending_check, safety_officer):
    api.force_authenticate(safety_officer)

    assert [c["id"] for c in api.get("/api/safety-checks/?status=PENDING").data] == [
        pending_check.pk
    ]
    assert api.get("/api/safety-checks/?status=APPROVED").data == []
    assert api.get("/api/safety-checks/?status=MAYBE").status_code == 400


def test_ac2d_a_decided_check_keeps_the_facts_that_were_reviewed(
    api, approved_check, safety_officer
):
    event = approved_check.event
    event.expected_attendance = 90
    event.save(update_fields=["expected_attendance"])
    api.force_authenticate(safety_officer)

    data = api.get(detail_url(approved_check)).data

    assert data["facts"]["expected_attendance"] == 120
    assert data["current_facts"] is None
    assert data["is_stale"] is True


def test_ac2e_staff_record_emergency_access_and_restrictions_on_the_venue(api, venue, venue_staff):
    """Supporting task: the venue safety information the review relies on."""
    api.force_authenticate(venue_staff)

    response = api.patch(
        f"/api/venues/{venue.pk}/",
        {"emergency_access": "Exit via east stairs.", "known_restrictions": "No smoke machines."},
        format="json",
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.emergency_access == "Exit via east stairs."
    assert venue.known_restrictions == "No smoke machines."


# --------------------------------------------------------------------------
# AC3 - decisions are recorded with name and time; comments for negatives
# --------------------------------------------------------------------------


def test_ac3a_approval_is_recorded_with_the_officers_name_and_time(
    api, pending_check, safety_officer, coordinator, lead
):
    api.force_authenticate(safety_officer)
    before = timezone.now()

    response = api.post(decide_url(pending_check), {"decision": "APPROVED"})

    assert response.status_code == 200
    assert response.data["status"] == SafetyStatus.APPROVED
    assert response.data["decided_by_name"] == "Sam Safety"
    pending_check.refresh_from_db()
    assert pending_check.decided_by == safety_officer
    assert before <= pending_check.decided_at <= timezone.now()
    told = Notification.objects.filter(kind=NotificationKind.SAFETY_DECIDED)
    assert {n.recipient for n in told} == {coordinator, lead}
    assert AuditLog.objects.filter(allowed=True, detail="decision=APPROVED").exists()


@pytest.mark.parametrize("decision", [SafetyStatus.REJECTED, SafetyStatus.CHANGES_REQUESTED])
def test_ac3b_rejecting_or_requesting_changes_needs_a_comment(
    api, pending_check, safety_officer, decision
):
    api.force_authenticate(safety_officer)

    blank = api.post(decide_url(pending_check), {"decision": decision, "comment": "   "})
    assert blank.status_code == 400
    assert blank.data["comment"] == ["A comment is required to reject or request changes."]
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.PENDING
    assert pending_check.decided_by is None

    response = api.post(
        decide_url(pending_check),
        {"decision": decision, "comment": "Fire exit 2 is blocked by the stage."},
    )
    assert response.status_code == 200
    assert response.data["comment"] == "Fire exit 2 is blocked by the stage."
    assert response.data["decided_by_name"] == "Sam Safety"


def test_ac3c_a_check_is_decided_only_once(api, approved_check, second_safety_officer):
    api.force_authenticate(second_safety_officer)

    response = api.post(decide_url(approved_check), {"decision": "REJECTED", "comment": "No."})

    assert response.status_code == 409
    approved_check.refresh_from_db()
    assert approved_check.status == SafetyStatus.APPROVED
    assert approved_check.decided_by.email == "safety@connectsphere.example"


def test_ac3d_an_unknown_decision_is_refused(api, pending_check, safety_officer):
    api.force_authenticate(safety_officer)
    assert api.post(decide_url(pending_check), {"decision": "MAYBE"}).status_code == 400
    with pytest.raises(SafetyRefused):
        decide(pending_check, safety_officer, "MAYBE")


@pytest.mark.django_db(transaction=True)
def test_ac3e_two_officers_deciding_at_once_cannot_both_succeed(
    ready_event, coordinator, safety_officer, second_safety_officer
):
    check = request_check(ready_event, coordinator)

    def attempt(officer, decision):
        close_old_connections()
        client = APIClient()
        client.force_authenticate(officer)
        try:
            return client.post(
                decide_url(check), {"decision": decision, "comment": "Exit blocked."}
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(
            pool.map(
                attempt,
                [safety_officer, second_safety_officer],
                [SafetyStatus.APPROVED, SafetyStatus.REJECTED],
            )
        )

    assert codes == [200, 409]
    check.refresh_from_db()
    assert check.status in (SafetyStatus.APPROVED, SafetyStatus.REJECTED)
    assert (
        Notification.objects.filter(
            recipient=coordinator, kind=NotificationKind.SAFETY_DECIDED
        ).count()
        == 1
    )


# --------------------------------------------------------------------------
# AC4 - after a rejection or requested changes the event stays in planning
# --------------------------------------------------------------------------


@pytest.mark.parametrize("decision", [SafetyStatus.REJECTED, SafetyStatus.CHANGES_REQUESTED])
def test_ac4a_event_stays_in_planning_and_the_coordinator_requests_a_new_check(
    api, pending_check, safety_officer, coordinator, venue_staff, decision
):
    event = pending_check.event
    decide(pending_check, safety_officer, decision, "Move to a hall with a second exit.")

    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    notice = Notification.objects.get(recipient=coordinator, kind=NotificationKind.SAFETY_DECIDED)
    assert "Move to a hall with a second exit." in notice.message
    assert "stays in planning" in notice.message

    # The coordinator revises the venue arrangement, then asks again.
    old = event.venue_bookings.get(status=BookingStatus.APPROVED)
    transition_booking(old, BookingStatus.WITHDRAWN, coordinator)
    approve_venue(event, make_venue("Skyline Room"), venue_staff)
    api.force_authenticate(coordinator)
    assert api.get(request_url(event)).data["can_request"] is True

    response = api.post(request_url(event), {"note": "Moved to Skyline Room."})

    assert response.status_code == 201
    assert response.data["facts"]["venues"][0]["venue"] == "Skyline Room"
    history = list(event.safety_checks.values_list("status", "comment"))
    assert history == [
        (SafetyStatus.PENDING, ""),
        (decision, "Move to a hall with a second exit."),
    ]


# --------------------------------------------------------------------------
# AC5 - no confirmation without an approved check (service guard; the confirm
# endpoint itself is SCRUM-58, gate G21)
# --------------------------------------------------------------------------


def test_ac5a_the_event_view_lists_the_safety_check_as_missing(api, ready_event, coordinator):
    api.force_authenticate(coordinator)
    data = api.get(request_url(ready_event)).data
    assert data["confirmation_gaps"] == ["Operational safety check: no approved check."]


def test_ac5b_confirmation_follows_the_real_request_and_approval(
    api, ready_event, coordinator, safety_officer
):
    with pytest.raises(ConfirmationBlocked):
        transition_event(ready_event, EventStatus.CONFIRMED, coordinator)

    api.force_authenticate(coordinator)
    check_id = api.post(request_url(ready_event), {}).data["id"]
    api.force_authenticate(safety_officer)
    api.post(f"/api/safety-checks/{check_id}/decide/", {"decision": "APPROVED"})

    api.force_authenticate(coordinator)
    assert api.get(request_url(ready_event)).data["confirmation_gaps"] == []
    event = transition_event(ready_event, EventStatus.CONFIRMED, coordinator)
    assert event.status == EventStatus.CONFIRMED


# --------------------------------------------------------------------------
# AC6 - changed arrangements make a check stale; a new one is needed
# --------------------------------------------------------------------------


def test_ac6a_losing_the_venue_after_confirmation_reopens_planning_and_blocks_reconfirmation(
    approved_check, coordinator, organiser
):
    event = transition_event(approved_check.event, EventStatus.CONFIRMED, coordinator)
    booking = event.venue_bookings.get(status=BookingStatus.APPROVED)

    transition_booking(booking, BookingStatus.WITHDRAWN, coordinator)

    event.refresh_from_db()
    approved_check.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert approved_check.status == SafetyStatus.SUPERSEDED
    reopened = Notification.objects.filter(kind=NotificationKind.PLANNING_REOPENED)
    assert {n.recipient for n in reopened} == {organiser}
    with pytest.raises(ConfirmationBlocked):
        transition_event(event, EventStatus.CONFIRMED, coordinator)


def test_ac6b_an_equipment_change_makes_the_approval_stale_and_a_new_check_requestable(
    api, approved_check, coordinator, tech
):
    event = approved_check.event
    EquipmentReservation.objects.update(quantity=1)
    EquipmentPlan.objects.get(event=event).requests.update(quantity=1)
    arrangements_changed(event, "Projectors reduced from 2 to 1.", tech)

    api.force_authenticate(coordinator)
    data = api.get(request_url(event)).data
    assert data["can_request"] is True
    assert data["checks"][0]["status"] == SafetyStatus.SUPERSEDED
    assert data["checks"][0]["superseded_reason"] == "Projectors reduced from 2 to 1."

    response = api.post(request_url(event), {})
    assert response.status_code == 201
    assert response.data["facts"]["equipment"][0]["quantity"] == 1


def test_ac6c_an_unreported_change_is_caught_when_a_new_check_is_requested(
    api, approved_check, coordinator
):
    event = approved_check.event
    event.preferred_end += timedelta(hours=2)
    event.save(update_fields=["preferred_end"])
    api.force_authenticate(coordinator)

    assert api.get(request_url(event)).data["can_request"] is True
    response = api.post(request_url(event), {})

    assert response.status_code == 201
    approved_check.refresh_from_db()
    assert approved_check.status == SafetyStatus.SUPERSEDED
    assert approved_check.superseded_reason == "The arrangements changed after it was requested."


def test_ac6d_a_pending_check_whose_arrangements_changed_cannot_be_approved(
    api, pending_check, safety_officer, second_safety_officer
):
    event = pending_check.event
    event.expected_attendance = 199
    event.save(update_fields=["expected_attendance"])
    api.force_authenticate(safety_officer)

    response = api.post(decide_url(pending_check), {"decision": "APPROVED"})

    assert response.status_code == 409
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.SUPERSEDED  # committed despite the refusal
    assert pending_check.decided_by is None
    assert Notification.objects.filter(
        recipient=second_safety_officer, kind=NotificationKind.SAFETY_SUPERSEDED
    ).exists()


# --------------------------------------------------------------------------
# AC7 - only Safety Officers decide; clients and attendees never see checks
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_COORDINATOR,
        Role.EVENT_COORDINATOR_LEAD,
        Role.VENUE_STAFF,
        Role.TECHNICAL_SUPPORT,
        Role.EVENT_ORGANISER,
        Role.ATTENDEE,
    ],
)
def test_ac7a_anyone_but_a_safety_officer_is_refused_and_audited(
    api, pending_check, coordinator, acme, role
):
    user = (
        coordinator
        if role == Role.EVENT_COORDINATOR
        else _make_user(f"{role.lower()}@x.example", role, acme)
    )
    api.force_authenticate(user)

    response = api.post(decide_url(pending_check), {"decision": "APPROVED"})

    assert response.status_code == 403
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.PENDING
    assert refusals(f"/api/safety-checks/{pending_check.pk}/decide/").get().actor == user


def test_ac7b_an_inactive_safety_officer_is_refused_and_audited(api, pending_check, safety_officer):
    safety_officer.is_active = False
    safety_officer.save(update_fields=["is_active"])
    api.force_authenticate(safety_officer)

    assert api.post(decide_url(pending_check), {"decision": "APPROVED"}).status_code == 403
    assert refusals("/decide/").get().detail == "only a Safety Officer"
    with pytest.raises(NotSafetyOfficer):
        decide(pending_check, safety_officer, SafetyStatus.APPROVED)


@pytest.mark.parametrize("who", ["organiser", "attendee", "anonymous"])
def test_ac7c_organisers_attendees_and_anonymous_users_cannot_see_safety_checks(
    api, pending_check, organiser, attendee, who
):
    if who != "anonymous":
        api.force_authenticate({"organiser": organiser, "attendee": attendee}[who])
    urls = ["/api/safety-checks/", detail_url(pending_check), request_url(pending_check.event)]
    for url in urls:
        assert api.get(url).status_code in (401, 403)
    assert refusals("safety-checks").count() == len(urls)


def test_ac7d_a_coordinator_sees_only_checks_on_their_own_events(
    api, pending_check, second_coordinator, coordinator
):
    api.force_authenticate(second_coordinator)
    assert api.get("/api/safety-checks/").data == []
    assert api.get(detail_url(pending_check)).status_code == 403
    assert api.get(request_url(pending_check.event)).status_code == 403
    assert refusals("safety-checks").count() == 2

    api.force_authenticate(coordinator)
    assert len(api.get("/api/safety-checks/").data) == 1


def test_ac7e_leads_can_read_but_not_decide(api, pending_check, lead):
    api.force_authenticate(lead)
    assert len(api.get("/api/safety-checks/").data) == 1
    assert api.get(detail_url(pending_check)).status_code == 200
    assert api.post(decide_url(pending_check), {"decision": "APPROVED"}).status_code == 403
