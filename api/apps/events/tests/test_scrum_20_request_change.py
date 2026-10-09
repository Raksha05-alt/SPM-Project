"""SCRUM-20 (US-19.1) - request a change to an event."""

import pytest

from apps.core.statuses import EventStatus
from apps.events.models import ChangeRequest, ChangeRequestStatus
from apps.events.tests.change_helpers import DAY, iso
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event


def url(event):
    return f"/api/events/{event.pk}/change-requests/"


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.SUBMITTED, EventStatus.CONFIRMED])
def test_ac1_the_client_states_what_should_change_and_why(
    signed_in_organiser, organiser, coordinator, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)
    new_start = event.preferred_start + DAY

    response = signed_in_organiser.post(
        url(event),
        {
            "description": "Move the conference one day later",
            "reason": "Our CEO is travelling",
            "proposed_start": iso(new_start),
            "proposed_end": iso(event.preferred_end + DAY),
            "proposed_attendance": 140,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    change = ChangeRequest.objects.get()
    assert (change.description, change.reason) == (
        "Move the conference one day later",
        "Our CEO is travelling",
    )
    assert change.proposed_start == new_start
    assert change.proposed_attendance == 140


@pytest.mark.django_db
def test_ac2_the_coordinator_is_notified_and_the_request_is_pending(
    signed_in_organiser, coordinator, event
):
    response = signed_in_organiser.post(url(event), {"description": "Add a breakout room"})

    assert response.data["status_display"] == "Pending"
    note = Notification.objects.get(recipient=coordinator)
    assert note.kind == NotificationKind.CHANGE_REQUESTED
    assert "Add a breakout room" in note.message


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"description": ""}, {"description": "   "}])
def test_ac3_a_request_without_a_description_is_prevented(signed_in_organiser, event, payload):
    response = signed_in_organiser.post(url(event), payload, format="json")

    assert response.status_code == 400
    assert response.data["description"] == ["Describe the change you want."]
    assert not ChangeRequest.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.REJECTED, EventStatus.DRAFT],
)
def test_ac4_closed_events_refuse_change_requests(signed_in_organiser, organiser, status):
    event = make_event(organiser, status=status)

    response = signed_in_organiser.post(url(event), {"description": "Anything"}, format="json")

    assert response.status_code == 409
    assert "cannot be requested" in response.data["detail"]


@pytest.mark.django_db
def test_ac5_the_client_sees_the_status_and_decision(signed_in_organiser, coordinator, event):
    ChangeRequest.objects.create(
        event=event,
        description="Smaller room",
        status=ChangeRequestStatus.REJECTED,
        decided_by=coordinator,
        decision_reason="No smaller room free that day",
    )

    [row] = signed_in_organiser.get(url(event)).data

    assert row["status_display"] == "Rejected"
    assert row["decision_reason"] == "No smaller room free that day"
    assert row["decided_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"proposed_attendance": 0}, "proposed_attendance"),
        ({"proposed_start": "2020-01-01T10:00:00+08:00"}, "proposed_start"),
    ],
)
def test_proposed_values_are_validated(signed_in_organiser, event, data, field):
    response = signed_in_organiser.post(
        url(event), {"description": "Change", **data}, format="json"
    )

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_a_proposed_period_must_end_after_it_starts(signed_in_organiser, event):
    response = signed_in_organiser.post(
        url(event),
        {"description": "Shorter", "proposed_end": iso(event.preferred_start)},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "The event must end after it starts."


@pytest.mark.django_db
def test_other_organisations_cannot_see_or_raise_changes(api, other_organiser, event):
    api.force_authenticate(other_organiser)

    assert api.get(url(event)).status_code == 403
    assert api.post(url(event), {"description": "x"}).status_code == 403


@pytest.mark.django_db
def test_coordinators_see_but_do_not_raise_change_requests(signed_in_coordinator, event):
    assert signed_in_coordinator.get(url(event)).status_code == 200
    assert signed_in_coordinator.post(url(event), {"description": "x"}).status_code == 403


@pytest.mark.django_db
def test_coordinators_cannot_reach_drafts(signed_in_coordinator, organiser):
    draft = make_event(organiser)

    assert signed_in_coordinator.get(url(draft)).status_code == 403
