"""SCRUM-79 - be notified of submissions, decisions and confirmations.

Every case drives the real API action and checks the persisted notices.

AC1 is tested under the effective interpretation recorded in the Sprint 4
guide (Week 7 change 5, SCRUM-89): a submission enters the unassigned Lead
queue, so the active Leads are notified; the coordinator is notified when
assigned. Auto-assignment is not restored. Record this with the PO before
closing SCRUM-79.
"""

import pytest
from django.db import transaction

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentPlan
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import MissingOccurrence, notify
from apps.safety.models import SafetyStatus
from apps.safety.services import arrangements_changed, decide, request_check
from apps.safety.tests.conftest import make_venue
from apps.venues.bookings import request_booking
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db


def notices(kind, **filters):
    return Notification.objects.filter(kind=kind, **filters)


def assign(api, lead, event, coordinator):
    event.refresh_from_db()
    api.force_authenticate(lead)
    return api.post(
        f"/api/events/{event.pk}/assign-coordinator/",
        {"coordinator_id": coordinator.pk, "expected_revision": event.assignment_revision},
        format="json",
    )


# --------------------------------------------------------------------------
# AC1 - submission reaches the Lead queue; assignment reaches the coordinator
# --------------------------------------------------------------------------


def test_ac1a_a_submission_notifies_every_active_lead_and_no_coordinator(
    api, organiser, lead, coordinator
):
    other_lead = _make_user("lead2@connectsphere.example", Role.EVENT_COORDINATOR_LEAD)
    retired = _make_user("lead3@connectsphere.example", Role.EVENT_COORDINATOR_LEAD)
    retired.is_active = False
    retired.save()
    draft = make_event(organiser)
    api.force_authenticate(organiser)

    response = api.post(f"/api/events/{draft.pk}/submit/")

    assert response.status_code == 200, response.data
    sent = notices(NotificationKind.SUBMITTED, event=draft)
    assert {n.recipient for n in sent} == {lead, other_lead}
    assert all(draft.name in n.message for n in sent)
    assert not Notification.objects.filter(recipient=coordinator).exists()


def test_ac1b_assignment_notifies_the_coordinator_and_reassignment_is_a_new_occurrence(
    api, lead, coordinator, second_coordinator, submitted_event
):
    assert assign(api, lead, submitted_event, coordinator).status_code == 200
    assert notices(NotificationKind.ASSIGNMENT, recipient=coordinator).count() == 1

    assert assign(api, lead, submitted_event, second_coordinator).status_code == 200

    assert notices(NotificationKind.ASSIGNMENT, recipient=second_coordinator).count() == 1
    # The previous coordinator hears about the reallocation as a second occurrence.
    assert notices(NotificationKind.ASSIGNMENT, recipient=coordinator).count() == 2


# --------------------------------------------------------------------------
# AC2 - the organiser hears every decision, with any reason given
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "payload", "kind", "expected"),
    [
        ("approve", {}, NotificationKind.APPROVED, "has been approved"),
        (
            "reject",
            {"reason": "The date clashes with a public holiday."},
            NotificationKind.REJECTED,
            "Reason: The date clashes with a public holiday.",
        ),
        (
            "request-clarification",
            {"message": "Please confirm the number of wheelchair users."},
            NotificationKind.CLARIFICATION,
            "Please confirm the number of wheelchair users.",
        ),
    ],
)
def test_ac2_the_organiser_is_notified_of_the_decision_and_reason(
    api, organiser, coordinator, action, payload, kind, expected
):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)

    response = api.post(f"/api/events/{event.pk}/{action}/", payload, format="json")

    assert response.status_code == 200, response.data
    [notice] = notices(kind, event=event)
    assert notice.recipient == organiser
    assert expected in notice.message
    assert event.name in notice.message


# --------------------------------------------------------------------------
# AC3 - the requesting coordinator hears the venue decision
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "payload", "expected"),
    [
        ("approve", {}, "Venue Staff approved Harbour Hall"),
        ("reject", {"reason": "Closed for repairs."}, "Reason: Closed for repairs."),
    ],
)
def test_ac3_the_coordinator_is_notified_of_the_venue_decision(
    api, planning_event, venue, coordinator, venue_staff, decision, payload, expected
):
    booking = request_booking(
        event=planning_event,
        venue=venue,
        requested_by=coordinator,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=120,
        layout="THEATRE",
    )
    api.force_authenticate(venue_staff)

    response = api.post(f"/api/venue-bookings/{booking.pk}/{decision}/", payload, format="json")

    assert response.status_code == 200, response.data
    [notice] = notices(NotificationKind.VENUE_DECIDED, event=planning_event)
    assert notice.recipient == coordinator
    assert expected in notice.message


# --------------------------------------------------------------------------
# AC4 - confirmation reaches the organiser and the staff involved
# --------------------------------------------------------------------------


@pytest.fixture
def approved_event(ready_event, coordinator, safety_officer):
    check = request_check(ready_event, coordinator)
    decide(check, safety_officer, SafetyStatus.APPROVED)
    ready_event.refresh_from_db()
    return ready_event


def test_ac4a_confirmation_notifies_the_organiser_and_the_involved_staff_only(
    api, approved_event, coordinator, organiser, venue_staff, tech
):
    uninvolved_venue = _make_user("venue2@connectsphere.example", Role.VENUE_STAFF)
    uninvolved_tech = _make_user("tech2@connectsphere.example", Role.TECHNICAL_SUPPORT)
    api.force_authenticate(coordinator)

    response = api.post(f"/api/events/{approved_event.pk}/confirm/")

    assert response.status_code == 200, response.data
    recipients = {n.recipient for n in notices(NotificationKind.EVENT_CONFIRMED)}
    # venue_staff approved the booking; tech reserved the equipment and approved the plan.
    assert recipients == {organiser, venue_staff, tech}
    assert uninvolved_venue not in recipients and uninvolved_tech not in recipients


def test_ac4b_a_later_reconfirmation_is_a_new_occurrence(
    api, approved_event, coordinator, organiser, safety_officer
):
    api.force_authenticate(coordinator)
    assert api.post(f"/api/events/{approved_event.pk}/confirm/").status_code == 200
    # An arrangement change returns it to Planning; a fresh check is approved.
    arrangements_changed(approved_event, "Projector moved to the stage.", coordinator)
    approved_event.refresh_from_db()
    assert approved_event.status == EventStatus.PLANNING
    decide(request_check(approved_event, coordinator), safety_officer, SafetyStatus.APPROVED)

    assert api.post(f"/api/events/{approved_event.pk}/confirm/").status_code == 200

    assert notices(NotificationKind.EVENT_CONFIRMED, recipient=organiser).count() == 2


def test_ac4c_deactivated_staff_are_not_notified(api, approved_event, coordinator, tech):
    User.objects.filter(pk=tech.pk).update(is_active=False)
    api.force_authenticate(coordinator)

    assert api.post(f"/api/events/{approved_event.pk}/confirm/").status_code == 200

    assert not notices(NotificationKind.EVENT_CONFIRMED, recipient=tech).exists()


# --------------------------------------------------------------------------
# AC5 - a notice identifies the event, what happened and when
# --------------------------------------------------------------------------


def test_ac5_each_notice_names_the_event_what_happened_and_when(api, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    api.force_authenticate(coordinator)
    api.post(f"/api/events/{event.pk}/approve/")
    api.force_authenticate(organiser)

    [data] = api.get("/api/notifications/").data

    assert data["event"] == event.pk
    assert data["event_name"] == event.name
    assert data["kind"] == NotificationKind.APPROVED
    assert data["kind_label"] == "Request approved"
    assert event.name in data["message"]
    assert data["created_at"]


# --------------------------------------------------------------------------
# The shared writer: occurrences, replays and rollback
# --------------------------------------------------------------------------


def test_w1_replaying_an_occurrence_never_duplicates_a_notice(organiser, coordinator):
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    for _ in range(2):
        notify(
            event=event,
            kind=NotificationKind.APPROVED,
            occurrence="event-status:99",
            recipients=[organiser, organiser.pk, None, coordinator],
            message="Approved.",
            skip=coordinator,
        )

    assert list(Notification.objects.values_list("recipient", "occurrence")) == [
        (organiser.pk, "APPROVED:event-status:99")
    ]


def test_w2_a_notice_needs_a_stable_occurrence(organiser):
    event = make_event(organiser)
    with pytest.raises(MissingOccurrence):
        notify(
            event=event,
            kind=NotificationKind.APPROVED,
            occurrence=" ",
            recipients=[organiser],
            message="x",
        )
    assert not Notification.objects.exists()


def test_w3_notices_roll_back_with_the_action_that_raised_them(api, organiser, lead):
    draft = make_event(organiser)

    with pytest.raises(RuntimeError), transaction.atomic():
        from apps.events.services import submit_event

        submit_event(draft, organiser)
        assert notices(NotificationKind.SUBMITTED).count() == 1
        raise RuntimeError("a later step of the action failed")

    draft.refresh_from_db()
    assert draft.status == EventStatus.DRAFT
    assert not Notification.objects.exists()
    assert not EventStatusHistory.objects.filter(event=draft).exists()


def test_w4_occurrences_come_from_persisted_records(api, organiser, coordinator, lead):
    draft = make_event(organiser)
    api.force_authenticate(organiser)
    api.post(f"/api/events/{draft.pk}/submit/")
    history = EventStatusHistory.objects.get(event=draft, to_status=EventStatus.SUBMITTED)

    notice = notices(NotificationKind.SUBMITTED).get()

    assert notice.occurrence == f"SUBMITTED:event-status:{history.pk}"


def test_w5_equipment_and_safety_producers_use_the_writer(
    planning_event, coordinator, tech, safety_officer
):
    from apps.safety.tests.conftest import approve_equipment, approve_venue

    approve_venue(
        planning_event, make_venue("Skyline Room"), _make_user("v@x.example", Role.VENUE_STAFF)
    )
    approve_equipment(planning_event, tech)
    check = request_check(planning_event, coordinator)

    requested = notices(NotificationKind.EQUIPMENT_REQUESTED).get()
    reserved = notices(NotificationKind.EQUIPMENT_UPDATED).get()
    safety = notices(NotificationKind.SAFETY_REQUESTED).get()
    assert requested.recipient == tech and requested.occurrence.startswith("EQUIPMENT_REQUESTED:")
    assert reserved.recipient == coordinator
    assert EquipmentPlan.objects.get(event=planning_event)
    assert (safety.target_type, safety.target_id) == ("SAFETY_CHECK", check.pk)
    assert not Notification.objects.filter(occurrence="").exists()
