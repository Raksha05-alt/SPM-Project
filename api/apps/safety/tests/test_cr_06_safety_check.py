"""Week 7 change 6 - Operational Safety Check by the Safety Officer.

CR6-AC1  Once venue and technical arrangements are in place, the coordinator sends
         the event for an Operational Safety Check (not before).
CR6-AC2  The Safety Officer reviews attendance, capacity and layout, emergency
         access and known restrictions, accessibility, and equipment.
CR6-AC3  The Safety Officer approves, rejects or requests changes, with a comment
         (required unless approving).
CR6-AC4  Rejecting or requesting changes returns the event to planning; the
         coordinator revises the arrangements and requests a new check.
CR6-AC5  The event cannot be confirmed until the Safety Officer has approved it.
CR6-AC6  A later change to the arrangements needs a new check (and a confirmed
         event returns to planning).
CR6-AC7  Only Safety Officers decide; access follows the role rules.
"""

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentType
from apps.equipment.tests.conftest import hold
from apps.events.models import EventChangeLog
from apps.events.tests.change_helpers import approve_change
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.tests.helpers import approve_safety
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


@pytest.fixture
def planned(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Charity Run Briefing",
        expected_attendance=120,
        accessibility_needs="Two wheelchair users",
    )


@pytest.fixture
def hall(db):
    return make_venue(
        name="Harbour Hall",
        capacity=150,
        safety_notes="Four exits; assembly point at the plaza.",
        accessibility_notes="Ramp at the side entrance",
    )


@pytest.fixture
def ready(planned, hall):
    """Venue approved and equipment reserved: ready for the safety check."""
    booking = book(planned, hall, attendance=120)
    projector = EquipmentType.objects.create(name="Projector", total_quantity=4)
    item = hold(planned, projector, 2).request
    return planned, booking, item


def request_check(client, event, note=""):
    return client.post(f"/api/events/{event.pk}/safety-checks/", {"note": note}, format="json")


def decide(client, check_id, decision, comment=""):
    return client.post(
        f"/api/safety-checks/{check_id}/decide/",
        {"decision": decision, "comment": comment},
        format="json",
    )


@pytest.fixture
def pending_check(coordinator, ready):
    from rest_framework.test import APIClient

    # Its own client, so it never changes who the test's shared client is signed in as.
    client = APIClient()
    client.force_authenticate(coordinator)
    response = request_check(client, ready[0], "Please review before Friday")
    assert response.status_code == 201, response.data
    return SafetyCheck.objects.get(pk=response.data["id"])


# --- CR6-AC1 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr6_ac1_the_coordinator_sends_a_ready_event_to_the_safety_officers(
    signed_in_coordinator, ready, safety_officer
):
    response = request_check(signed_in_coordinator, ready[0], "Outdoor queue expected")

    assert response.status_code == 201, response.data
    assert response.data["status"] == SafetyStatus.PENDING
    assert response.data["request_note"] == "Outdoor queue expected"
    note = Notification.objects.get(recipient=safety_officer)
    assert note.kind == NotificationKind.SAFETY_REQUESTED


@pytest.mark.django_db
def test_cr6_ac1_arrangements_must_be_in_place_first(signed_in_coordinator, planned, hall):
    book(planned, hall, status=BookingStatus.PENDING)

    response = request_check(signed_in_coordinator, planned)

    assert response.status_code == 409
    assert response.data["missing"][0]["arrangement"] == "Venue"
    assert not SafetyCheck.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.APPROVED, EventStatus.CONFIRMED])
def test_cr6_ac1_only_an_event_in_planning_is_checked(
    signed_in_coordinator, organiser, coordinator, hall, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)
    book(event, hall)

    assert request_check(signed_in_coordinator, event).status_code == 409


@pytest.mark.django_db
def test_cr6_ac1_one_check_at_a_time(signed_in_coordinator, pending_check):
    response = request_check(signed_in_coordinator, pending_check.event)

    assert response.status_code == 409
    assert SafetyCheck.objects.count() == 1


@pytest.mark.django_db
def test_cr6_ac1_only_the_assigned_coordinator_requests_it(
    api, second_coordinator, organiser, lead, ready
):
    for who in (second_coordinator, organiser, lead):
        api.force_authenticate(who)
        assert request_check(api, ready[0]).status_code == 403
    assert not SafetyCheck.objects.exists()


@pytest.mark.django_db
def test_cr6_ac1_readiness_says_when_the_check_can_be_requested(signed_in_coordinator, ready):
    data = signed_in_coordinator.get(f"/api/events/{ready[0].pk}/readiness/").data

    assert data["arrangements"] == []
    assert data["can_request_safety_check"] is True
    assert data["can_confirm"] is False
    assert data["missing"] == [
        {"arrangement": "Safety", "detail": "The operational safety check has not been requested."}
    ]


# --- CR6-AC2 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr6_ac2_the_officer_sees_the_facts_to_review(signed_in_safety, pending_check):
    [row] = signed_in_safety.get("/api/safety-checks/", {"status": "PENDING"}).data

    facts = row["current_facts"]
    assert facts["expected_attendance"] == 120
    assert facts["accessibility_needs"] == "Two wheelchair users"
    [venue] = facts["venues"]
    assert (venue["venue"], venue["capacity"], venue["attendance"]) == ("Harbour Hall", 150, 120)
    assert venue["safety_notes"] == "Four exits; assembly point at the plaza."
    assert venue["wheelchair_access"] is True
    assert facts["equipment"] == [
        {"equipment": "Projector", "quantity": 2, "technical_requirements": ""}
    ]
    assert facts["concerns"] == []
    assert row["facts"]["event_name"] == "Charity Run Briefing"  # snapshot at request time


@pytest.mark.django_db
def test_cr6_ac2_the_system_points_out_visible_concerns(organiser, coordinator):
    from apps.safety.services import safety_facts

    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        expected_attendance=80,
        accessibility_needs="Step-free access",
    )
    book(event, make_venue(name="Old Annex", capacity=60, wheelchair_access=False), attendance=80)

    concerns = safety_facts(event)["concerns"]
    assert "Old Annex: 80 attendees booked for a capacity of 60." in concerns
    assert "Old Annex has no recorded step-free access." in concerns
    assert "Old Annex has no emergency access or restriction notes recorded." in concerns
    assert "Expected attendance of 80 exceeds the combined capacity of 60." in concerns


@pytest.mark.django_db
def test_cr6_ac2_the_officer_can_open_the_event_but_not_change_it(signed_in_safety, pending_check):
    event = pending_check.event

    assert signed_in_safety.get(f"/api/events/{event.pk}/").status_code == 200
    assert (
        signed_in_safety.patch(f"/api/events/{event.pk}/", {"name": "x"}, format="json").status_code
        == 403
    )


@pytest.mark.django_db
def test_cr6_ac2_the_officer_cannot_open_events_not_sent_for_a_check(signed_in_safety, planned):
    assert signed_in_safety.get(f"/api/events/{planned.pk}/").status_code == 403
    assert signed_in_safety.get("/api/events/").data == []


# --- CR6-AC3 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr6_ac3_approval_is_recorded_and_the_coordinator_told(
    signed_in_safety, safety_officer, coordinator, pending_check
):
    response = decide(signed_in_safety, pending_check.pk, "APPROVED", "Exits clear.")

    assert response.status_code == 200, response.data
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.APPROVED
    assert pending_check.decided_by == safety_officer
    assert pending_check.comment == "Exits clear."
    assert Notification.objects.filter(
        recipient=coordinator, kind=NotificationKind.SAFETY_DECIDED
    ).exists()
    entry = EventChangeLog.objects.get(field="Operational safety check")
    assert entry.new_value == "Approved: Exits clear."


@pytest.mark.django_db
def test_cr6_ac3_approval_needs_no_comment(signed_in_safety, pending_check):
    assert decide(signed_in_safety, pending_check.pk, "APPROVED").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["REJECTED", "CHANGES_REQUESTED"])
@pytest.mark.parametrize("comment", ["", "   "])
def test_cr6_ac3_rejecting_or_asking_for_changes_needs_a_comment(
    signed_in_safety, pending_check, decision, comment
):
    response = decide(signed_in_safety, pending_check.pk, decision, comment)

    assert response.status_code == 400
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.PENDING


@pytest.mark.django_db
def test_cr6_ac3_an_unknown_decision_is_refused(signed_in_safety, pending_check):
    assert decide(signed_in_safety, pending_check.pk, "MAYBE", "x").status_code == 400


@pytest.mark.django_db
def test_cr6_ac3_a_check_is_decided_once(signed_in_safety, pending_check):
    decide(signed_in_safety, pending_check.pk, "APPROVED")

    assert (
        decide(signed_in_safety, pending_check.pk, "REJECTED", "Changed my mind").status_code == 409
    )


# --- CR6-AC4 -----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["REJECTED", "CHANGES_REQUESTED"])
def test_cr6_ac4_a_refusal_keeps_the_event_in_planning_for_revision(
    api, safety_officer, coordinator, pending_check, decision
):
    api.force_authenticate(safety_officer)
    decide(api, pending_check.pk, decision, "Crowd flow blocks the north exit.")
    event = pending_check.event
    event.refresh_from_db()
    api.force_authenticate(coordinator)

    confirm = api.post(f"/api/events/{event.pk}/confirm/")
    again = request_check(api, event, "Moved the registration desk")

    assert event.status == EventStatus.PLANNING
    assert confirm.status_code == 409
    assert "Crowd flow blocks the north exit." in confirm.data["missing"][-1]["detail"]
    assert again.status_code == 201
    note = Notification.objects.filter(
        recipient=coordinator, kind=NotificationKind.SAFETY_DECIDED
    ).first()
    assert "revise the affected arrangements" in note.message


# --- CR6-AC5 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr6_ac5_a_pending_check_blocks_confirmation(signed_in_coordinator, pending_check):
    response = signed_in_coordinator.post(f"/api/events/{pending_check.event_id}/confirm/")

    assert response.status_code == 409
    assert response.data["missing"] == [
        {
            "arrangement": "Safety",
            "detail": "The operational safety check is awaiting the Safety Officer.",
        }
    ]


@pytest.mark.django_db
def test_cr6_ac5_the_coordinator_confirms_once_safety_has_approved(
    api, safety_officer, coordinator, pending_check
):
    api.force_authenticate(safety_officer)
    decide(api, pending_check.pk, "APPROVED")
    api.force_authenticate(coordinator)

    readiness = api.get(f"/api/events/{pending_check.event_id}/readiness/").data
    response = api.post(f"/api/events/{pending_check.event_id}/confirm/")

    assert readiness["can_confirm"] is True
    assert response.status_code == 200
    assert response.data["status"] == EventStatus.CONFIRMED


# --- CR6-AC6 -----------------------------------------------------------------


@pytest.mark.django_db
def test_cr6_ac6_changing_equipment_supersedes_the_approval(signed_in_coordinator, ready):
    event, _, item = ready
    check = approve_safety(event)

    signed_in_coordinator.patch(
        f"/api/equipment-requests/{item.pk}/", {"quantity": 3}, format="json"
    )

    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED
    assert "Quantity changed" in check.superseded_reason


@pytest.mark.django_db
def test_cr6_ac6_withdrawing_a_venue_supersedes_the_approval(signed_in_coordinator, ready):
    event, booking, _ = ready
    check = approve_safety(event)

    signed_in_coordinator.post(
        f"/api/venue-bookings/{booking.pk}/withdraw/", {"confirm": True}, format="json"
    )

    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED


@pytest.mark.django_db
def test_cr6_ac6_a_significant_edit_supersedes_a_pending_check_and_tells_the_officer(
    api, coordinator, safety_officer, pending_check
):
    api.force_authenticate(coordinator)

    api.patch(f"/api/events/{pending_check.event_id}/", {"expected_attendance": 140}, format="json")

    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.SUPERSEDED
    assert Notification.objects.filter(
        recipient=safety_officer,
        kind=NotificationKind.SAFETY_DECIDED,
        message__contains="no longer applies",
    ).exists()


@pytest.mark.django_db
def test_cr6_ac6_an_ordinary_edit_keeps_the_approval(signed_in_coordinator, ready):
    event = ready[0]
    check = approve_safety(event)

    signed_in_coordinator.patch(
        f"/api/events/{event.pk}/", {"description": "Agenda"}, format="json"
    )

    check.refresh_from_db()
    assert check.status == SafetyStatus.APPROVED


@pytest.mark.django_db
def test_cr6_ac6_a_confirmed_event_changed_through_a_request_needs_every_check_again(
    api, organiser, coordinator, hall
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    book(event, hall)
    check = approve_safety(event)

    approve_change(api, event, {"expected_attendance": 140})

    check.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert check.status == SafetyStatus.SUPERSEDED
    response = api.post(f"/api/events/{event.pk}/confirm/")
    assert response.status_code == 409


# --- CR6-AC7 -----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["coordinator", "lead", "venue_staff"])
def test_cr6_ac7_only_a_safety_officer_decides(api, request, pending_check, role):
    api.force_authenticate(request.getfixturevalue(role))

    response = decide(api, pending_check.pk, "APPROVED")

    assert response.status_code == 403
    pending_check.refresh_from_db()
    assert pending_check.status == SafetyStatus.PENDING
    assert AuditLog.objects.filter(allowed=False).exists()


@pytest.mark.django_db
def test_cr6_ac7_coordinators_see_their_own_checks_and_leads_see_all(
    api, second_coordinator, lead, pending_check
):
    api.force_authenticate(second_coordinator)
    assert api.get("/api/safety-checks/").data == []
    assert api.get(f"/api/events/{pending_check.event_id}/safety-checks/").status_code == 403
    api.force_authenticate(lead)
    assert len(api.get("/api/safety-checks/").data) == 1


@pytest.mark.django_db
def test_cr6_ac7_clients_do_not_see_the_safety_check(api, organiser, pending_check):
    api.force_authenticate(organiser)

    assert "safety_check" not in api.get(f"/api/events/{pending_check.event_id}/").data
    assert api.get("/api/safety-checks/").status_code == 403


@pytest.mark.django_db
def test_cr6_ac7_an_unknown_status_filter_is_refused(signed_in_safety):
    assert signed_in_safety.get("/api/safety-checks/", {"status": "NOPE"}).status_code == 400


@pytest.mark.django_db
def test_cr6_ac7_the_event_history_lists_every_check(signed_in_coordinator, pending_check):
    rows = signed_in_coordinator.get(f"/api/events/{pending_check.event_id}/safety-checks/").data

    assert [row["status"] for row in rows] == [SafetyStatus.PENDING]
