"""SCRUM-16 (US-17.1) - reserve equipment for an event."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequestStatus, EquipmentReservation
from apps.equipment.services import available_quantity
from apps.equipment.tests.conftest import HOUR, hold, make_request
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event


def url(item):
    return f"/api/equipment-requests/{item.pk}/reserve/"


@pytest.fixture
def rival(organiser, coordinator):
    return make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala")


@pytest.mark.django_db
def test_ac1_reserving_records_it_against_the_event_and_notifies_the_coordinator(
    signed_in_tech, coordinator, event, projector
):
    item = make_request(event, projector, 4)

    response = signed_in_tech.post(url(item))

    assert response.status_code == 201, response.data
    assert response.data["status"] == EquipmentRequestStatus.RESERVED
    reservation = EquipmentReservation.objects.get()
    assert (reservation.event, reservation.quantity) == (event, 4)
    assert (reservation.start, reservation.end) == (event.preferred_start, event.preferred_end)
    note = Notification.objects.get(recipient=coordinator)
    assert note.kind == NotificationKind.EQUIPMENT_RESERVED
    assert "4 x Projector reserved" in note.message


@pytest.mark.django_db
def test_ac2_reserved_units_are_deducted_for_overlapping_events(
    signed_in_tech, event, projector, rival
):
    signed_in_tech.post(url(make_request(event, projector, 4)))

    overlapping = available_quantity(
        projector, event.preferred_start + HOUR, event.preferred_end + HOUR
    )
    later = available_quantity(projector, event.preferred_end, event.preferred_end + HOUR)

    assert (overlapping, later) == (6, 10)


@pytest.mark.django_db
def test_ac3_more_than_is_available_is_refused_with_the_available_quantity(
    signed_in_tech, event, projector, rival
):
    hold(rival, projector, 7)
    item = make_request(event, projector, 4)

    response = signed_in_tech.post(url(item))

    assert response.status_code == 409
    assert response.data["available_quantity"] == 3
    assert response.data["detail"] == "Only 3 x Projector available for this period; 4 requested."
    assert not item.reservations.exists()


@pytest.mark.django_db
def test_ac4_out_of_service_equipment_cannot_be_reserved(signed_in_tech, event, projector):
    projector.out_of_service_quantity = 10
    projector.out_of_service_reason = "Water damage"
    projector.save()

    response = signed_in_tech.post(url(make_request(event, projector, 1)))

    assert response.status_code == 409
    assert "out of service (Water damage)" in response.data["detail"]


@pytest.mark.django_db
def test_ac4_units_under_maintenance_reduce_what_can_be_reserved(signed_in_tech, event, projector):
    projector.out_of_service_quantity = 8
    projector.save()

    response = signed_in_tech.post(url(make_request(event, projector, 3)))

    assert response.status_code == 409
    assert response.data["available_quantity"] == 2


@pytest.mark.django_db
def test_ac5_the_reserving_user_and_time_are_stored(signed_in_tech, tech_staff, event, projector):
    response = signed_in_tech.post(url(make_request(event, projector, 2)))

    reservation = EquipmentReservation.objects.get()
    assert reservation.reserved_by == tech_staff
    assert reservation.reserved_at is not None
    assert response.data["reservations"][0]["reserved_by_name"] == "Tariq Tech"


@pytest.mark.django_db
def test_only_the_outstanding_quantity_is_reserved(signed_in_tech, event, projector):
    item = hold(event, projector, 2).request
    item.quantity = 5
    item.status = EquipmentRequestStatus.REQUESTED
    item.save()

    response = signed_in_tech.post(url(item))

    assert response.data["reserved_quantity"] == 5
    assert [r["quantity"] for r in response.data["reservations"]] == [2, 3]


@pytest.mark.django_db
def test_a_fully_reserved_request_cannot_be_reserved_again(signed_in_tech, event, projector):
    item = hold(event, projector, 2).request

    response = signed_in_tech.post(url(item))

    assert response.status_code == 409
    assert response.data["detail"] == "Everything requested is already reserved."


@pytest.mark.django_db
def test_a_withdrawn_request_cannot_be_reserved(signed_in_tech, event, projector):
    item = make_request(event, projector, 2, status=EquipmentRequestStatus.WITHDRAWN)

    assert signed_in_tech.post(url(item)).status_code == 409


@pytest.mark.django_db
def test_equipment_is_not_reserved_for_a_closed_event(signed_in_tech, event, projector):
    item = make_request(event, projector, 2)
    event.status = EventStatus.CANCELLED
    event.save()

    response = signed_in_tech.post(url(item))

    assert response.status_code == 409
    assert "Cancelled" in response.data["detail"]


@pytest.mark.django_db
def test_an_event_without_a_period_cannot_have_equipment_reserved(signed_in_tech, event, projector):
    item = make_request(event, projector, 2)
    event.preferred_start = event.preferred_end = None
    event.save()

    response = signed_in_tech.post(url(item))

    assert response.status_code == 409
    assert "no date and time" in response.data["detail"]


@pytest.mark.django_db
def test_only_technical_staff_reserve(signed_in_coordinator, event, projector):
    assert signed_in_coordinator.post(url(make_request(event, projector, 2))).status_code == 403


@pytest.mark.django_db
def test_released_reservations_do_not_hold_units(event, projector, rival):
    hold(rival, projector, 10, released_at=timezone.now())

    assert available_quantity(projector, event.preferred_start, event.preferred_end) == 10
