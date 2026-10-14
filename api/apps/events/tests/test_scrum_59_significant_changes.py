"""SCRUM-59 (US-07.2) - significant changes distinguished from ordinary edits.

Week 7 clarifications: "once an event is Confirmed, information fields cannot be
changed directly" - a confirmed event changes through a change request, and a
significant change "requires the event to go through the change process and all
checks are required before it is approved and confirmed again". Before
confirmation the coordinator edits directly and is warned as before.
"""

import pytest

from apps.core.statuses import EventStatus
from apps.events.models import EventChangeLog
from apps.events.tests.change_helpers import HOUR, approve_change, confirmed_event, iso
from apps.notifications.models import Notification, NotificationKind
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


@pytest.fixture
def planning(organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    booking = book(event, make_venue(capacity=150))
    return event, booking


def patch(client, event, data):
    return client.patch(f"/api/events/{event.pk}/", data, format="json")


SIGNIFICANT = [
    ({"expected_attendance": 130}, "expected attendance"),
    ({"required_layout": "CLASSROOM"}, "room layout"),
    ({"accessibility_needs": "Hearing loop"}, "accessibility needs"),
    ({"equipment_notes": "Two extra microphones"}, "equipment requirements"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("data", "label"), SIGNIFICANT)
def test_ac1_requirement_changes_during_planning_are_flagged_as_significant(
    signed_in_coordinator, planning, data, label
):
    event, _ = planning

    response = patch(signed_in_coordinator, event, data)

    assert response.status_code == 200, response.data
    change = response.data["significant_change"]
    assert change["changed_fields"] == [label]
    assert EventChangeLog.objects.filter(event=event).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("data", "label"), SIGNIFICANT)
def test_ac1_a_confirmed_event_cannot_be_edited_directly(signed_in_coordinator, setup, data, label):
    event = setup[0]

    response = patch(signed_in_coordinator, event, data)

    assert response.status_code == 403
    assert "change request" in response.data["detail"]
    assert not EventChangeLog.objects.filter(event=event).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("data", "label"), SIGNIFICANT)
def test_ac1_an_approved_significant_change_marks_arrangements_and_reopens_planning(
    api, setup, data, label
):
    event = setup[0]

    approve_change(api, event, data)

    entry = EventChangeLog.objects.get(event=event, field=next(iter(data)))
    assert entry.significant is True
    assert event.status == EventStatus.PLANNING


@pytest.mark.django_db
def test_ac1_a_new_time_marks_venue_equipment_and_tells_attendees(api, setup):
    event, booking, item, attendee = setup

    approve_change(
        api,
        event,
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
    )

    booking.refresh_from_db()
    item.refresh_from_db()
    assert booking.review_required and item.review_required
    assert Notification.objects.filter(
        recipient=attendee, kind=NotificationKind.EVENT_CHANGED
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("data", [{"description": "New agenda"}, {"purpose": "Briefing"}])
def test_ac2_descriptions_and_notes_are_ordinary_edits(signed_in_coordinator, planning, data):
    event, booking = planning

    response = patch(signed_in_coordinator, event, data)

    assert response.data["significant_change"] == {
        "significant": False,
        "changed_fields": [],
        "affected_arrangements": [],
    }
    assert EventChangeLog.objects.get(event=event).significant is False
    booking.refresh_from_db()
    assert not booking.review_required
    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_ac3_venue_staff_technical_staff_and_the_client_are_notified(
    api, setup, venue_staff, tech_staff, organiser
):
    event = setup[0]

    approve_change(
        api,
        event,
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
    )

    assert Notification.objects.filter(
        recipient=venue_staff, kind=NotificationKind.REVIEW_NEEDED
    ).exists()
    assert Notification.objects.filter(
        recipient=tech_staff, kind=NotificationKind.REVIEW_NEEDED
    ).exists()
    assert Notification.objects.filter(
        recipient=organiser, kind=NotificationKind.CHANGE_DECIDED
    ).exists()


@pytest.mark.django_db
def test_ac4_affected_arrangements_are_marked_for_review(api, setup):
    event, booking, item, _ = setup

    approve_change(api, event, {"equipment_notes": "Spare lamp"})

    item.refresh_from_db()
    booking.refresh_from_db()
    assert item.review_required is True
    assert item.review_reason == "The event's equipment requirements changed."
    # Equipment notes do not touch the venue.
    assert booking.review_required is False


@pytest.mark.django_db
def test_ac4_a_venue_change_marks_the_booking_for_review(api, setup):
    event, booking, item, _ = setup

    approve_change(api, event, {"expected_attendance": 125})

    booking.refresh_from_db()
    item.refresh_from_db()
    assert booking.review_required is True
    assert booking.review_reason == "The event's expected attendance changed."
    assert item.review_required is False


@pytest.mark.django_db
def test_a_new_time_with_too_little_equipment_says_so(api, organiser, coordinator, setup):
    from apps.equipment.tests.conftest import hold

    event, _, item, _ = setup
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    hold(rival, item.equipment_type, 4, event.preferred_start + HOUR, event.preferred_end + HOUR)

    approve_change(
        api,
        event,
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
    )

    item.refresh_from_db()
    assert item.review_reason == "Only 1 available in the new period; 3 reserved."
