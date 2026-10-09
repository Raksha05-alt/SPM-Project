"""Small behaviours not tied to a single acceptance criterion."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.impact import shifted
from apps.events.models import (
    ChangeRequest,
    ClarificationRequest,
    CoordinatorAssignment,
    EventChangeLog,
)
from apps.events.services import NotPermitted, _as_text, cancel_event
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event


@pytest.mark.django_db
def test_event_records_describe_themselves(organiser, coordinator):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    clarification = ClarificationRequest.objects.create(event=event, message="Budget?")
    assignment = CoordinatorAssignment.objects.create(event=event, coordinator=coordinator)
    entry = EventChangeLog.objects.create(
        event=event, field="name", previous_value="A", new_value="B"
    )
    change = ChangeRequest.objects.create(event=event, description="Later")
    note = Notification.objects.create(
        recipient=organiser, event=event, kind=NotificationKind.STATUS_CHANGED, message="Hi"
    )

    assert str(clarification) == f"Clarification on {event.pk} (open)"
    assert str(assignment) == f"{event.pk}: None -> {coordinator.pk}"
    assert str(entry) == f"{event.pk}.name: 'A' -> 'B'"
    assert str(change) == f"Change to event {event.pk} (Pending)"
    assert str(note)


def test_empty_values_are_logged_as_blank_text():
    assert _as_text(None) == ""
    assert _as_text(True) == "Yes"


@pytest.mark.django_db
def test_the_cancel_service_refuses_another_organisation(other_organiser, organiser):
    event = make_event(organiser, status=EventStatus.SUBMITTED)

    with pytest.raises(NotPermitted):
        cancel_event(event, other_organiser)


@pytest.mark.django_db
def test_coordinators_cannot_delete_events(signed_in_coordinator, organiser):
    event = make_event(organiser, status=EventStatus.SUBMITTED)

    assert signed_in_coordinator.delete(f"/api/events/{event.pk}/").status_code == 403


def test_a_booking_stays_put_when_the_event_had_no_time():
    class Booking:
        start = timezone.now()
        end = start + timezone.timedelta(hours=1)

    old = {"preferred_start": None, "preferred_end": None}
    new = {"preferred_start": timezone.now(), "preferred_end": timezone.now()}

    assert shifted(Booking, old, new) == (Booking.start, Booking.end)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "step", ["approve", "reject", "request-clarification", "confirm", "complete", "reassign"]
)
def test_a_client_cannot_take_coordinator_decisions_on_their_own_event(
    signed_in_organiser, organiser, step
):
    # A request awaiting clarification is open to its client, so only the view's
    # own rule stops them here.
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW)

    response = signed_in_organiser.post(f"/api/events/{event.pk}/{step}/", {}, format="json")

    assert response.status_code == 403
