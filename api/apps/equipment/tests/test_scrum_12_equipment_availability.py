"""SCRUM-12 (US-16.1) - check equipment availability for an event period."""

import pytest

from apps.core.statuses import EventStatus
from apps.equipment.tests.conftest import HOUR, another_coordinator, hold, make_request
from conftest import make_event

URL = "/api/equipment/availability/"


@pytest.fixture
def rival(organiser, coordinator):
    return make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala")


def row_for(response, name="Projector"):
    return next(r for r in response.data["results"] if r["name"] == name)


@pytest.mark.django_db
def test_ac1_choosing_an_event_shows_equipment_for_its_period(signed_in_tech, event, projector):
    response = signed_in_tech.get(URL, {"event": event.pk})

    assert response.status_code == 200
    assert response.data["event"] == event.pk
    assert response.data["start"] == event.preferred_start
    assert [r["name"] for r in response.data["results"]] == ["Projector"]


@pytest.mark.django_db
def test_ac1_choosing_a_date_and_time_shows_equipment_for_that_period(
    signed_in_tech, event, projector
):
    response = signed_in_tech.get(
        URL,
        {
            "start": event.preferred_start.isoformat(),
            "end": (event.preferred_start + HOUR).isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.data["event"] is None
    assert row_for(response)["available_quantity"] == 10


@pytest.mark.django_db
def test_ac1_an_invalid_period_is_explained(signed_in_tech, projector):
    response = signed_in_tech.get(URL, {"start": "nonsense", "end": "x"})

    assert response.status_code == 400


@pytest.mark.django_db
def test_ac1_an_event_without_a_date_cannot_be_checked(signed_in_tech, organiser, coordinator):
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=None,
        preferred_end=None,
    )

    response = signed_in_tech.get(URL, {"event": event.pk})

    assert response.status_code == 400
    assert response.data["detail"] == "The event has no date and time yet."


@pytest.mark.django_db
def test_ac2_the_available_quantity_of_each_type_is_shown(signed_in_tech, event, projector, rival):
    hold(rival, projector, 3)

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert (row["total_quantity"], row["reserved_for_other_events"], row["available_quantity"]) == (
        10,
        3,
        7,
    )


@pytest.mark.django_db
def test_ac3_equipment_reserved_elsewhere_for_the_period_is_unavailable(
    signed_in_tech, event, projector, rival
):
    hold(rival, projector, 10)

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert (row["available_quantity"], row["status"]) == (0, "Unavailable")


@pytest.mark.django_db
def test_ac3_reservations_outside_the_period_do_not_count(signed_in_tech, event, projector, rival):
    hold(rival, projector, 10, event.preferred_end, event.preferred_end + HOUR)

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert row["available_quantity"] == 10


@pytest.mark.django_db
def test_ac4_damaged_or_maintenance_units_are_unavailable_whatever_the_period(
    signed_in_tech, event, projector
):
    projector.out_of_service_quantity = 4
    projector.out_of_service_reason = "Lamp replacement"
    projector.save()

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert row["available_quantity"] == 6
    assert row["out_of_service_reason"] == "Lamp replacement"


@pytest.mark.django_db
def test_ac5_a_shortfall_against_the_request_is_shown(signed_in_tech, event, projector, rival):
    hold(rival, projector, 8)
    make_request(event, projector, 5)

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert (row["requested_quantity"], row["shortfall"], row["status"]) == (5, 3, "Short by 3")


@pytest.mark.django_db
def test_ac5_units_already_reserved_for_this_event_are_not_a_shortfall(
    signed_in_tech, event, projector
):
    hold(event, projector, 10)

    row = row_for(signed_in_tech.get(URL, {"event": event.pk}))

    assert (row["reserved_for_this_event"], row["shortfall"]) == (10, 0)


@pytest.mark.django_db
def test_ac6_the_assigned_coordinator_can_check_their_event(
    signed_in_coordinator, event, projector
):
    assert signed_in_coordinator.get(URL, {"event": event.pk}).status_code == 200


@pytest.mark.django_db
def test_ac6_a_coordinator_cannot_check_without_their_event(api, event, projector):
    api.force_authenticate(another_coordinator())

    assert api.get(URL, {"event": event.pk}).status_code == 403
    assert api.get(URL).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["signed_in_organiser", "signed_in_venue_staff"])
def test_ac6_other_roles_are_refused(request, fixture, event):
    client = request.getfixturevalue(fixture)

    assert client.get(URL, {"event": event.pk}).status_code == 403


@pytest.mark.django_db
def test_the_event_must_be_an_id(signed_in_tech):
    assert signed_in_tech.get(URL, {"event": "x"}).status_code == 400
