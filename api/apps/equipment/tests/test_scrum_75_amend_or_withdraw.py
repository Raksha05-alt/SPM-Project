"""SCRUM-75 (US-15.2) - amend or withdraw an equipment request."""

import pytest

from apps.equipment.models import EquipmentRequestStatus, EquipmentReservation
from apps.equipment.services import available_quantity
from apps.equipment.tests.conftest import another_coordinator, hold, make_request
from apps.notifications.models import Notification, NotificationKind


def url(item, step=""):
    return f"/api/equipment-requests/{item.pk}/{step}"


@pytest.mark.django_db
def test_ac1_changing_an_unreserved_request_is_saved_and_staff_notified(
    signed_in_coordinator, tech_staff, event, projector
):
    item = make_request(event, projector, 4, technical_requirements="HDMI")

    response = signed_in_coordinator.patch(
        url(item), {"quantity": 6, "technical_requirements": "HDMI and VGA"}, format="json"
    )

    assert response.status_code == 200, response.data
    item.refresh_from_db()
    assert (item.quantity, item.technical_requirements) == (6, "HDMI and VGA")
    note = Notification.objects.get(recipient=tech_staff)
    assert note.kind == NotificationKind.EQUIPMENT_CHANGED
    assert "Quantity changed from 4 to 6." in note.message


@pytest.mark.django_db
def test_ac1_an_unchanged_save_records_nothing(signed_in_coordinator, event, projector):
    item = make_request(event, projector, 4)

    response = signed_in_coordinator.patch(url(item), {"quantity": 4}, format="json")

    assert response.status_code == 200
    assert response.data["changes"] == []
    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_ac1_the_quantity_must_stay_above_zero(signed_in_coordinator, event, projector):
    item = make_request(event, projector, 4)

    response = signed_in_coordinator.patch(url(item), {"quantity": 0}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_ac1_the_event_and_type_cannot_be_changed(signed_in_coordinator, event, projector):
    item = make_request(event, projector, 4)

    response = signed_in_coordinator.patch(
        url(item), {"equipment_type": projector.pk}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_ac2_reducing_a_reserved_request_releases_the_surplus(
    signed_in_coordinator, event, projector
):
    reservation = hold(event, projector, 6)
    item = reservation.request

    response = signed_in_coordinator.patch(url(item), {"quantity": 2}, format="json")

    assert response.status_code == 200
    assert response.data["reserved_quantity"] == 2
    assert response.data["status"] == EquipmentRequestStatus.RESERVED
    released = EquipmentReservation.objects.get(released_at__isnull=False)
    assert (released.quantity, released.release_reason) == (4, "Quantity reduced")
    assert available_quantity(projector, event.preferred_start, event.preferred_end) == 8


@pytest.mark.django_db
def test_ac2_raising_a_reserved_request_asks_for_the_extra_units(
    signed_in_coordinator, event, projector
):
    item = hold(event, projector, 2).request

    response = signed_in_coordinator.patch(url(item), {"quantity": 5}, format="json")

    assert response.data["status"] == EquipmentRequestStatus.REQUESTED
    assert response.data["reserved_quantity"] == 2


@pytest.mark.django_db
def test_ac2_surplus_is_released_across_several_reservations(
    signed_in_coordinator, event, projector
):
    first = hold(event, projector, 2)
    item = first.request
    item.quantity = 5
    item.save()
    EquipmentReservation.objects.create(
        request=item,
        event=event,
        equipment_type=projector,
        quantity=3,
        start=first.start,
        end=first.end,
    )

    response = signed_in_coordinator.patch(url(item), {"quantity": 1}, format="json")

    assert response.data["reserved_quantity"] == 1
    assert "4 reserved unit(s) released." in response.data["changes"][0]["description"]


@pytest.mark.django_db
def test_ac3_withdrawing_releases_the_reservation_and_marks_it_withdrawn(
    signed_in_coordinator, tech_staff, event, projector
):
    item = hold(event, projector, 3).request

    response = signed_in_coordinator.post(url(item, "withdraw/"))

    assert response.status_code == 200
    assert response.data["status"] == EquipmentRequestStatus.WITHDRAWN
    assert response.data["reserved_quantity"] == 0
    assert available_quantity(projector, event.preferred_start, event.preferred_end) == 10
    assert "3 reserved unit(s) released" in Notification.objects.get(recipient=tech_staff).message


@pytest.mark.django_db
def test_ac3_a_withdrawn_request_cannot_be_withdrawn_or_changed_again(
    signed_in_coordinator, event, projector
):
    item = make_request(event, projector, 2)
    signed_in_coordinator.post(url(item, "withdraw/"))

    again = signed_in_coordinator.post(url(item, "withdraw/"))
    changed = signed_in_coordinator.patch(url(item), {"quantity": 3}, format="json")

    assert again.status_code == 409
    assert changed.status_code == 409


@pytest.mark.django_db
def test_ac4_the_change_user_and_time_are_shown(signed_in_coordinator, event, projector):
    item = make_request(event, projector, 2, technical_requirements="")
    signed_in_coordinator.patch(url(item), {"technical_requirements": "Spare bulb"}, format="json")

    response = signed_in_coordinator.post(url(item, "withdraw/"))

    changes = response.data["changes"]
    assert [c["description"] for c in changes] == [
        'Technical requirements changed from "" to "Spare bulb".',
        "Request withdrawn.",
    ]
    assert {c["changed_by_name"] for c in changes} == {"Cora Coordinator"}
    assert all(c["changed_at"] for c in changes)
    assert response.data["withdrawn_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "withdraw"])
def test_only_the_assigned_coordinator_can_change_a_request(api, event, projector, method):
    item = make_request(event, projector, 2)
    api.force_authenticate(another_coordinator())

    if method == "patch":
        response = api.patch(url(item), {"quantity": 3}, format="json")
    else:
        response = api.post(url(item, "withdraw/"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_technical_staff_cannot_amend_requests(signed_in_tech, event, projector):
    item = make_request(event, projector, 2)

    assert signed_in_tech.patch(url(item), {"quantity": 3}, format="json").status_code == 403


@pytest.mark.django_db
def test_ac2_only_the_newest_reservation_is_trimmed_when_it_covers_the_surplus(
    signed_in_coordinator, event, projector
):
    first = hold(event, projector, 2)
    item = first.request
    item.quantity = 5
    item.save()
    EquipmentReservation.objects.create(
        request=item,
        event=event,
        equipment_type=projector,
        quantity=3,
        start=first.start,
        end=first.end,
    )

    response = signed_in_coordinator.patch(url(item), {"quantity": 4}, format="json")

    assert sorted(r["quantity"] for r in response.data["reservations"] if not r["released_at"]) == [
        2,
        2,
    ]
