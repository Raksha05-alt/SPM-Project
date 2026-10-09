"""SCRUM-74 (US-15.1) - record the equipment an event requires."""

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequest
from apps.equipment.tests.conftest import another_coordinator, make_request
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event

URL = "/api/equipment-requests/"


def payload(event, equipment_type, **overrides):
    data = {
        "event": event.pk,
        "equipment_type": equipment_type.pk,
        "quantity": 4,
        "technical_requirements": "HDMI input, 5000 lumens",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_ac1_type_quantity_and_technical_requirements_are_recorded(
    signed_in_coordinator, event, projector
):
    response = signed_in_coordinator.post(URL, payload(event, projector), format="json")

    assert response.status_code == 201, response.data
    item = EquipmentRequest.objects.get()
    assert (item.equipment_type, item.quantity, item.technical_requirements) == (
        projector,
        4,
        "HDMI input, 5000 lumens",
    )
    assert response.data["status_display"] == "Requested"


@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [0, -1])
def test_ac2_a_quantity_of_zero_or_less_is_blocked_with_a_reason(
    signed_in_coordinator, event, projector, quantity
):
    response = signed_in_coordinator.post(
        URL, payload(event, projector, quantity=quantity), format="json"
    )

    assert response.status_code == 400
    assert response.data["quantity"] == ["The quantity must be at least 1."]
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_ac2_missing_items_are_identified(signed_in_coordinator):
    response = signed_in_coordinator.post(URL, {}, format="json")

    assert response.status_code == 400
    assert response.data["quantity"] == ["Enter the quantity required."]
    assert response.data["equipment_type"] == ["Choose the equipment type."]
    assert response.data["event"] == ["Choose the event this equipment is for."]


@pytest.mark.django_db
def test_ac3_technical_staff_see_every_requested_item(signed_in_tech, event, projector):
    from apps.equipment.models import EquipmentType

    mic = EquipmentType.objects.create(name="Microphone", total_quantity=6)
    make_request(event, projector, 4, technical_requirements="HDMI")
    make_request(event, mic, 2, technical_requirements="Wireless")

    response = signed_in_tech.get(URL, {"event": event.pk})

    assert response.status_code == 200
    assert [
        (r["equipment_name"], r["quantity"], r["technical_requirements"]) for r in response.data
    ] == [("Projector", 4, "HDMI"), ("Microphone", 2, "Wireless")]


@pytest.mark.django_db
def test_ac4_the_requester_and_time_are_recorded_and_technical_staff_notified(
    signed_in_coordinator, coordinator, tech_staff, event, projector
):
    response = signed_in_coordinator.post(URL, payload(event, projector), format="json")

    item = EquipmentRequest.objects.get()
    assert item.requested_by == coordinator
    assert item.created_at is not None
    assert response.data["requested_by_name"] == "Cora Coordinator"
    note = Notification.objects.get(recipient=tech_staff)
    assert note.kind == NotificationKind.EQUIPMENT_REQUESTED
    assert "4 x Projector" in note.message
    assert AuditLog.objects.filter(action="POST /api/equipment-requests/", allowed=True).exists()


@pytest.mark.django_db
def test_ac5_a_coordinator_who_is_not_assigned_is_refused(api, event, projector):
    api.force_authenticate(another_coordinator())

    response = api.post(URL, payload(event, projector), format="json")

    assert response.status_code == 403
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_ac5_technical_staff_cannot_add_requests(signed_in_tech, event, projector):
    assert signed_in_tech.post(URL, payload(event, projector), format="json").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["signed_in_organiser", "signed_in_venue_staff"])
def test_other_roles_cannot_reach_equipment_requests(request, fixture):
    client = request.getfixturevalue(fixture)

    assert client.get(URL).status_code == 403


@pytest.mark.django_db
def test_drafts_cannot_have_equipment_requested(
    signed_in_coordinator, organiser, coordinator, projector
):
    draft = make_event(organiser, coordinator=coordinator)

    response = signed_in_coordinator.post(URL, payload(draft, projector), format="json")

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [EventStatus.SUBMITTED, EventStatus.CANCELLED, EventStatus.COMPLETED]
)
def test_equipment_is_requested_only_for_events_being_planned(
    signed_in_coordinator, organiser, coordinator, projector, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)

    response = signed_in_coordinator.post(URL, payload(event, projector), format="json")

    assert response.status_code == 409
    assert "once the event is approved" in response.data["detail"]


@pytest.mark.django_db
def test_the_event_filter_must_be_an_id(signed_in_tech):
    assert signed_in_tech.get(URL, {"event": "x"}).status_code == 400


@pytest.mark.django_db
def test_the_catalogue_lists_equipment_types(signed_in_coordinator, projector):
    response = signed_in_coordinator.get("/api/equipment/")

    assert [row["name"] for row in response.data] == ["Projector"]
