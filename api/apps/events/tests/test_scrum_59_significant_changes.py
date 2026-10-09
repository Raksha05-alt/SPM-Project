"""SCRUM-59 (US-07.2) - significant changes distinguished from ordinary edits."""

import pytest

from apps.events.models import EventChangeLog
from apps.events.tests.change_helpers import HOUR, confirmed_event, iso
from apps.notifications.models import Notification, NotificationKind


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


def patch(client, event, data):
    return client.patch(f"/api/events/{event.pk}/", data, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("data", "label"),
    [
        ({"expected_attendance": 130}, "expected attendance"),
        ({"required_layout": "CLASSROOM"}, "room layout"),
        ({"accessibility_needs": "Hearing loop"}, "accessibility needs"),
        ({"equipment_notes": "Two extra microphones"}, "equipment requirements"),
    ],
)
def test_ac1_requirement_changes_are_significant_and_warn_about_arrangements(
    signed_in_coordinator, setup, data, label
):
    event = setup[0]

    response = patch(signed_in_coordinator, event, data)

    assert response.status_code == 200, response.data
    change = response.data["significant_change"]
    assert change["significant"] is True
    assert change["changed_fields"] == [label]
    assert change["affected_arrangements"]
    assert EventChangeLog.objects.get(event=event).significant is True


@pytest.mark.django_db
def test_ac1_a_new_time_warns_about_venue_equipment_and_attendees(signed_in_coordinator, setup):
    event = setup[0]

    response = patch(
        signed_in_coordinator,
        event,
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
    )

    assert response.data["significant_change"]["affected_arrangements"] == [
        "Venue booking for Harbour Hall",
        "3 x Projector",
        "1 registered attendee(s)",
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("data", [{"description": "New agenda"}, {"purpose": "Briefing"}])
def test_ac2_descriptions_and_notes_are_ordinary_edits(signed_in_coordinator, setup, data):
    event, booking, item, _ = setup

    response = patch(signed_in_coordinator, event, data)

    assert response.data["significant_change"] == {
        "significant": False,
        "changed_fields": [],
        "affected_arrangements": [],
    }
    assert EventChangeLog.objects.get(event=event).significant is False
    booking.refresh_from_db()
    item.refresh_from_db()
    assert not booking.review_required and not item.review_required
    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_ac3_venue_staff_technical_staff_and_the_client_are_notified(
    signed_in_coordinator, setup, venue_staff, tech_staff, organiser
):
    event = setup[0]

    patch(
        signed_in_coordinator,
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
    client_note = Notification.objects.get(recipient=organiser, kind=NotificationKind.EVENT_CHANGED)
    assert "significant change" in client_note.message


@pytest.mark.django_db
def test_ac4_affected_arrangements_are_marked_for_review(signed_in_coordinator, setup):
    event, booking, item, _ = setup

    patch(signed_in_coordinator, event, {"equipment_notes": "Spare lamp"})

    item.refresh_from_db()
    booking.refresh_from_db()
    assert item.review_required is True
    assert item.review_reason == "The event's equipment requirements changed."
    # Equipment notes do not touch the venue.
    assert booking.review_required is False


@pytest.mark.django_db
def test_ac4_a_venue_change_marks_the_booking_for_review(signed_in_coordinator, setup):
    event, booking, item, _ = setup

    patch(signed_in_coordinator, event, {"expected_attendance": 125})

    booking.refresh_from_db()
    item.refresh_from_db()
    assert booking.review_required is True
    assert booking.review_reason == "The event's expected attendance changed."
    assert item.review_required is False


@pytest.mark.django_db
def test_a_new_time_with_too_little_equipment_says_so(
    signed_in_coordinator, organiser, coordinator, setup
):
    from apps.core.statuses import EventStatus
    from apps.equipment.tests.conftest import hold
    from conftest import make_event

    event, _, item, _ = setup
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    hold(rival, item.equipment_type, 4, event.preferred_start + HOUR, event.preferred_end + HOUR)

    patch(
        signed_in_coordinator,
        event,
        {
            "preferred_start": iso(event.preferred_start + HOUR),
            "preferred_end": iso(event.preferred_end + HOUR),
        },
    )

    item.refresh_from_db()
    assert item.review_reason == "Only 1 available in the new period; 3 reserved."
