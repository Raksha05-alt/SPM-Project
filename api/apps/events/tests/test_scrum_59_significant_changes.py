"""SCRUM-59 - Significant changes distinguished from ordinary edits (Sprint 4 gate ASSESS).

As an Event Coordinator, I want the system to distinguish a change that affects
confirmed arrangements from an ordinary edit, so that venue, equipment and
attendee arrangements are reconsidered only when they need to be.

Week 9 / Week 7 change 6: once an event is Confirmed its fields cannot be
changed directly; a date, time or attendance change goes through the change
process and every check before it is confirmed again.

At ASSESS this story delivers AC1 (flagged significant, affected arrangements
warned, event not edited) and the AC3 notices when a significant change is
approved. AC4 (arrangements marked for review) and AC5 (back to Planning and a
new Safety check) are completed when the change is applied, under SCRUM-80
(guide section 5). AC2 was withdrawn in Jira.

Case IDs follow the Sprint 4 guide: S4-59-<case>.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.events.change_requests import SIGNIFICANT_FIELDS, is_significant
from apps.events.models import EventChangeRequest, EventFieldChange
from apps.events.tests.test_scrum_78_review_change import END, NEXT_DAY, START, change_for

# The shared SCRUM-78 scenario's fixtures, re-exported for pytest.
from apps.events.tests.test_scrum_78_review_change import coordinator_api as coordinator_api
from apps.events.tests.test_scrum_78_review_change import gala as gala
from apps.events.tests.test_scrum_78_review_change import projector as projector
from apps.events.tests.test_scrum_78_review_change import venue as venue
from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import destination
from conftest import make_event


def decide(api, change, decision="APPROVE", reason="Agreed."):
    return api.post(
        f"/api/change-requests/{change.pk}/decide/",
        {"decision": decision, "reason": reason},
        format="json",
    )


def staff_notices(role):
    return Notification.objects.filter(kind=NotificationKind.CHANGE_DECIDED, recipient__role=role)


# S4-59-01 - AC1: date, time, attendance, venue or equipment requirements are significant.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "proposed",
    [
        {"preferred_start": START + NEXT_DAY, "preferred_end": END + NEXT_DAY},
        {"preferred_end": END + NEXT_DAY},
        {"expected_attendance": 140},
        {"required_layout": "BANQUET"},
        {"accessibility_needs": "Step-free access for two guests."},
        {"equipment_notes": "Add two lapel microphones."},
    ],
    ids=["date", "time", "attendance", "layout", "accessibility", "equipment"],
)
def test_s4_59_01_ac1_key_changes_are_recorded_as_significant(organiser, gala, proposed):
    change = change_for(gala, organiser, **proposed)

    change.refresh_from_db()
    assert change.significant is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "proposed",
    [
        {"name": "Annual Gala 2027"},
        {"purpose": "Partner celebration"},
        {"description": "New blurb"},
        {},
    ],
    ids=["name", "purpose", "description", "nothing-proposed"],
)
def test_s4_59_01_ordinary_changes_are_not_significant(organiser, gala, proposed):
    change = change_for(gala, organiser, **proposed)

    change.refresh_from_db()
    assert change.significant is False


@pytest.mark.django_db
def test_s4_59_01_naming_an_arrangement_is_significant(organiser, gala):
    from apps.events.change_requests import request_change

    booking = gala.venue_bookings.get()
    change = request_change(
        event=gala,
        requested_by=organiser,
        description="Use a different room.",
        reason="More space.",
        target_bookings=[booking.pk],
    )

    assert change.significant is True


@pytest.mark.django_db
def test_s4_59_01_ac1_the_flag_is_shown_with_the_request(api, organiser, gala):
    change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(organiser)

    [row] = api.get(f"/api/events/{gala.pk}/change-requests/").data

    assert row["significant"] is True


@pytest.mark.django_db
def test_s4_59_01_ac1_the_coordinator_is_warned_which_arrangements_may_be_affected(
    coordinator_api, organiser, gala
):
    change = change_for(gala, organiser, expected_attendance=151)

    data = coordinator_api.get(f"/api/change-requests/{change.pk}/impact/").data

    assert (data["significant"], data["significant_fields"]) == (True, ["expected_attendance"])
    assert [row["venue"] for row in data["venue_bookings"]] == ["Harbour Hall"]
    assert data["warnings"]


@pytest.mark.django_db
@pytest.mark.parametrize("event_status", [EventStatus.SUBMITTED, EventStatus.PLANNING])
def test_s4_59_01_significance_does_not_depend_on_the_event_stage(
    organiser, coordinator, event_status
):
    event = make_event(organiser, status=event_status, coordinator=coordinator)

    change = change_for(event, organiser, expected_attendance=200)

    assert change.significant is True


@pytest.mark.django_db
def test_s4_59_01_ac1_the_confirmed_event_is_not_edited_directly(api, organiser, coordinator, gala):
    change_for(gala, organiser, expected_attendance=140)
    api.force_authenticate(coordinator)

    # Week 9: a Confirmed event changes only through a change request.
    response = api.patch(f"/api/events/{gala.pk}/", {"expected_attendance": 140}, format="json")

    assert response.status_code == 403
    gala.refresh_from_db()
    assert gala.expected_attendance == 120
    assert not EventFieldChange.objects.filter(event=gala).exists()


def test_s4_59_01_the_rule_names_exactly_the_agreed_fields():
    assert SIGNIFICANT_FIELDS == (
        "preferred_start",
        "preferred_end",
        "expected_attendance",
        "required_layout",
        "accessibility_needs",
        "equipment_notes",
    )
    assert is_significant({}) is False
    assert is_significant({}, target_equipment_requests=[4]) is True


@pytest.mark.django_db
def test_s4_59_01_requests_made_before_the_flag_are_classified(organiser, gala):
    significant = change_for(gala, organiser, expected_attendance=140)
    ordinary = change_for(gala, organiser, name="New name")
    EventChangeRequest.objects.update(significant=False)
    migration = importlib.import_module("apps.events.migrations.0016_change_request_significant")

    migration.classify_existing(django_apps, None)

    flags = dict(EventChangeRequest.objects.values_list("pk", "significant"))
    assert flags == {significant.pk: True, ordinary.pk: False}


# S4-59-03 - AC3: an approved significant change reaches the affected staff and organiser.


@pytest.mark.django_db
def test_s4_59_03_ac3_affected_venue_and_technical_staff_are_notified_on_approval(
    coordinator_api, organiser, venue_staff, gala
):
    tech = User.objects.create_user(
        username="tech", email="tech@example.com", role=Role.TECHNICAL_SUPPORT
    )
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    assert decide(coordinator_api, change).status_code == 200

    [venue_notice] = staff_notices(Role.VENUE_STAFF)
    [tech_notice] = staff_notices(Role.TECHNICAL_SUPPORT)
    assert venue_notice.recipient == venue_staff
    assert tech_notice.recipient == tech
    assert venue_notice.message.startswith(
        'An approved change to "Annual Gala" affects its venue bookings'
    )
    assert tech_notice.message.startswith(
        'An approved change to "Annual Gala" affects its equipment'
    )
    assert venue_notice.message.endswith(
        "It will be sent to you for review before anything changes."
    )
    # Each opens the staff member's own screen for the event.
    assert destination(venue_notice, venue_staff).path == "/venues/requests"
    assert destination(tech_notice, tech).path == f"/equipment/plans/{gala.pk}"
    # The organiser hears the decision.
    assert (
        Notification.objects.filter(
            kind=NotificationKind.CHANGE_DECIDED, recipient=organiser
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_s4_59_03_ac3_only_staff_whose_arrangements_are_affected_hear(
    coordinator_api, organiser, venue_staff, gala
):
    User.objects.create_user(username="tech", email="tech@example.com", role=Role.TECHNICAL_SUPPORT)
    change = change_for(gala, organiser, expected_attendance=140)

    decide(coordinator_api, change)

    assert staff_notices(Role.VENUE_STAFF).count() == 1
    assert not staff_notices(Role.TECHNICAL_SUPPORT).exists()


@pytest.mark.django_db
def test_s4_59_03_a_rejected_change_tells_only_the_organiser(
    coordinator_api, organiser, venue_staff, gala
):
    change = change_for(
        gala, organiser, preferred_start=START + NEXT_DAY, preferred_end=END + NEXT_DAY
    )

    decide(coordinator_api, change, decision="REJECT", reason="The venue is unavailable.")

    assert not staff_notices(Role.VENUE_STAFF).exists()
    assert (
        Notification.objects.filter(
            kind=NotificationKind.CHANGE_DECIDED, recipient=organiser
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_s4_59_03_an_approved_ordinary_change_tells_no_staff(
    coordinator_api, organiser, venue_staff, gala
):
    change = change_for(gala, organiser, name="Annual Gala 2027")

    decide(coordinator_api, change)

    assert not staff_notices(Role.VENUE_STAFF).exists()


@pytest.mark.django_db
def test_s4_59_03_a_replayed_staff_notice_is_not_duplicated(
    organiser, coordinator, venue_staff, gala
):
    from apps.events.change_requests import _staff_notices
    from apps.events.impact import assess_change

    change = change_for(gala, organiser, expected_attendance=140)
    assessment = assess_change(change)

    _staff_notices(change, gala, assessment, coordinator)
    _staff_notices(change, gala, assessment, coordinator)

    assert staff_notices(Role.VENUE_STAFF).count() == 1
