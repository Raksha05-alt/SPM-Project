"""SCRUM-76 (US-16.2) - see which events are holding equipment I need."""

import datetime

import pytest

from apps.core.statuses import EventStatus
from apps.equipment.tests.conftest import hold
from conftest import make_event


def url(equipment):
    return f"/api/equipment/{equipment.pk}/holders/"


@pytest.fixture
def rival(organiser, coordinator):
    return make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala")


@pytest.mark.django_db
def test_ac1_the_events_holding_it_and_their_dates_are_listed(
    signed_in_tech, event, projector, rival
):
    reservation = hold(rival, projector, 6)

    response = signed_in_tech.get(url(projector), {"event": event.pk})

    assert response.status_code == 200
    [holder] = response.data["holding_events"]
    assert (holder["event_name"], holder["quantity"]) == ("Gala", 6)
    assert (holder["start"], holder["end"]) == (reservation.start, reservation.end)


@pytest.mark.django_db
def test_ac2_out_of_service_reason_and_expected_return_are_shown(signed_in_tech, event, projector):
    projector.out_of_service_quantity = 10
    projector.out_of_service_reason = "Sent for repair"
    projector.expected_return = datetime.date(2030, 1, 15)
    projector.save()

    data = signed_in_tech.get(url(projector), {"event": event.pk}).data

    assert data["out_of_service_reason"] == "Sent for repair"
    assert data["expected_return"] == datetime.date(2030, 1, 15)


@pytest.mark.django_db
def test_ac3_only_planning_details_are_shown(signed_in_tech, event, projector, rival):
    hold(rival, projector, 2)

    [holder] = signed_in_tech.get(url(projector), {"event": event.pk}).data["holding_events"]

    assert set(holder) == {
        "event",
        "event_name",
        "event_status",
        "start",
        "end",
        "quantity",
        "coordinator_name",
    }
    assert holder["coordinator_name"] == "Cora Coordinator"


@pytest.mark.django_db
def test_ac3_an_unassigned_holder_shows_no_coordinator(signed_in_tech, organiser, event, projector):
    unassigned = make_event(organiser, status=EventStatus.CONFIRMED)
    hold(unassigned, projector, 1)

    [holder] = signed_in_tech.get(url(projector), {"event": event.pk}).data["holding_events"]

    assert holder["coordinator_name"] is None


@pytest.mark.django_db
def test_ac4_equipment_held_by_a_cancelled_event_is_available_again(
    signed_in_tech, event, projector, rival
):
    hold(rival, projector, 10)
    rival.status = EventStatus.CANCELLED
    rival.save()

    holders = signed_in_tech.get(url(projector), {"event": event.pk}).data["holding_events"]
    availability = signed_in_tech.get("/api/equipment/availability/", {"event": event.pk})

    assert holders == []
    assert availability.data["results"][0]["available_quantity"] == 10


@pytest.mark.django_db
def test_holders_are_refused_to_coordinators_of_other_events(api, event, projector):
    from apps.equipment.tests.conftest import another_coordinator

    api.force_authenticate(another_coordinator())

    assert api.get(url(projector), {"event": event.pk}).status_code == 403
