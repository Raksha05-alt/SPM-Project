"""SCRUM-58 (US-06.4) - confirm an event after essential arrangements are complete."""

import pytest

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequestStatus, EquipmentType
from apps.equipment.tests.conftest import hold, make_request
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification
from apps.venues.models import BookingStatus
from apps.venues.tests.helpers import book, make_user
from conftest import make_event, make_venue


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


@pytest.fixture
def hall(db):
    return make_venue()


@pytest.fixture
def projector(db):
    return EquipmentType.objects.create(name="Projector", total_quantity=10)


def url(event):
    return f"/api/events/{event.pk}/confirm/"


@pytest.mark.django_db
def test_ac1_an_event_with_approved_venue_and_reserved_equipment_can_be_confirmed(
    signed_in_coordinator, event, hall, projector
):
    book(event, hall)
    hold(event, projector, 3)

    response = signed_in_coordinator.post(url(event))

    assert response.status_code == 200, response.data
    assert response.data["status"] == EventStatus.CONFIRMED


@pytest.mark.django_db
def test_ac1_an_event_needing_no_equipment_is_confirmed_with_its_venue(
    signed_in_coordinator, event, hall
):
    book(event, hall)

    assert signed_in_coordinator.post(url(event)).status_code == 200


@pytest.mark.django_db
def test_ac2_no_venue_blocks_confirmation(signed_in_coordinator, event):
    response = signed_in_coordinator.post(url(event))

    assert response.status_code == 409
    assert response.data["missing"] == [
        {"arrangement": "Venue", "detail": "No venue booking has been approved."}
    ]
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING


@pytest.mark.django_db
def test_ac2_each_missing_arrangement_is_listed(signed_in_coordinator, event, hall, projector):
    book(event, hall, status=BookingStatus.PENDING)
    book(event, make_venue(name="Annex"), status=BookingStatus.REJECTED)
    make_request(event, projector, 4)
    mic = EquipmentType.objects.create(name="Microphone", total_quantity=2)
    make_request(
        event, mic, 2, status=EquipmentRequestStatus.UNAVAILABLE, unavailable_reason="Broken"
    )
    make_request(event, projector, 1, status=EquipmentRequestStatus.WITHDRAWN)

    response = signed_in_coordinator.post(url(event))

    assert response.status_code == 409
    assert [m["detail"] for m in response.data["missing"]] == [
        "The request for Harbour Hall is awaiting a decision from Venue Staff.",
        "4 x Projector is awaiting reservation by Technical Support Staff (0 of 4 reserved).",
        "2 x Microphone is unavailable: Broken",
    ]


@pytest.mark.django_db
def test_ac2_arrangements_needing_review_block_confirmation(
    signed_in_coordinator, event, hall, projector
):
    book(event, hall, review_required=True, review_reason="Attendance exceeds capacity")
    reservation = hold(event, projector, 2)
    reservation.request.review_required = True
    reservation.request.review_reason = "Date changed"
    reservation.request.save()

    response = signed_in_coordinator.post(url(event))

    assert [m["detail"] for m in response.data["missing"]] == [
        "The booking for Harbour Hall needs review: Attendance exceeds capacity",
        "2 x Projector needs review: Date changed",
    ]


@pytest.mark.django_db
def test_ac3_staff_recording_equipment_unavailable_tells_the_client_why(
    api, tech_staff, organiser, coordinator, event, projector
):
    item = make_request(event, projector, 4)
    api.force_authenticate(tech_staff)

    response = api.post(
        f"/api/equipment-requests/{item.pk}/mark-unavailable/",
        {"reason": "All units booked for maintenance"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == EquipmentRequestStatus.UNAVAILABLE
    assert "unavailable: All units booked for maintenance" in (
        Notification.objects.get(recipient=organiser).message
    )
    assert Notification.objects.filter(recipient=coordinator).exists()
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING


@pytest.mark.django_db
def test_ac3_staff_recording_a_venue_unavailable_tells_the_client_why(
    signed_in_venue_staff, organiser, event, hall
):
    pending = book(event, hall, status=BookingStatus.PENDING)

    signed_in_venue_staff.post(
        f"/api/venue-bookings/{pending.pk}/reject/", {"reason": "Flooded"}, format="json"
    )

    assert "Flooded" in Notification.objects.get(recipient=organiser).message


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"reason": " "}])
def test_ac3_an_unavailable_outcome_needs_a_reason(signed_in_tech, event, projector, payload):
    item = make_request(event, projector, 1)

    response = signed_in_tech.post(
        f"/api/equipment-requests/{item.pk}/mark-unavailable/", payload, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_ac3_only_an_outstanding_request_can_be_marked_unavailable(
    signed_in_tech, event, projector
):
    item = hold(event, projector, 1).request

    response = signed_in_tech.post(
        f"/api/equipment-requests/{item.pk}/mark-unavailable/", {"reason": "x"}, format="json"
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_ac3_amending_an_unavailable_request_puts_it_back_in_the_queue(
    signed_in_coordinator, event, projector
):
    item = make_request(
        event, projector, 4, status=EquipmentRequestStatus.UNAVAILABLE, unavailable_reason="x"
    )

    response = signed_in_coordinator.patch(
        f"/api/equipment-requests/{item.pk}/", {"quantity": 2}, format="json"
    )

    assert response.data["status"] == EquipmentRequestStatus.REQUESTED
    assert response.data["unavailable_reason"] == ""


@pytest.mark.django_db
def test_ac4_confirming_records_the_coordinator_and_time(
    signed_in_coordinator, coordinator, event, hall
):
    book(event, hall)

    response = signed_in_coordinator.post(url(event))

    event.refresh_from_db()
    assert event.confirmed_by == coordinator
    assert event.confirmed_at is not None
    assert response.data["confirmed_by_name"] == "Cora Coordinator"
    assert EventStatusHistory.objects.filter(
        event=event, to_status=EventStatus.CONFIRMED, changed_by=coordinator
    ).exists()


@pytest.mark.django_db
def test_ac5_the_client_sees_the_confirmed_arrangements_and_is_notified(
    api, coordinator, organiser, event, hall, projector
):
    book(event, hall)
    hold(event, projector, 3)
    api.force_authenticate(coordinator)
    api.post(url(event))
    api.force_authenticate(organiser)

    data = api.get(f"/api/events/{event.pk}/").data

    assert [v["venue"] for v in data["confirmed_arrangements"]["venues"]] == ["Harbour Hall"]
    assert data["confirmed_arrangements"]["equipment"] == [
        {"equipment": "Projector", "quantity": 3}
    ]
    message = Notification.objects.get(recipient=organiser).message
    assert "moved from Planning to Confirmed" in message
    assert "Harbour Hall from" in message and "3 x Projector" in message


@pytest.mark.django_db
def test_arrangements_are_not_shown_before_confirmation(signed_in_organiser, event):
    assert (
        signed_in_organiser.get(f"/api/events/{event.pk}/").data["confirmed_arrangements"] is None
    )


@pytest.mark.django_db
def test_venue_and_technical_staff_involved_are_notified(
    signed_in_coordinator, venue_staff, tech_staff, event, hall, projector
):
    book(event, hall, decided_by=venue_staff)
    hold(event, projector, 1, reserved_by=tech_staff)

    signed_in_coordinator.post(url(event))

    assert "is confirmed for" in Notification.objects.get(recipient=venue_staff).message
    assert "is confirmed for" in Notification.objects.get(recipient=tech_staff).message


@pytest.mark.django_db
def test_only_the_assigned_coordinator_can_confirm(api, signed_in_organiser, event, hall):
    book(event, hall)

    assert signed_in_organiser.post(url(event)).status_code == 403
    api.force_authenticate(make_user("c2@connectsphere.example", Role.EVENT_COORDINATOR))
    assert api.post(url(event)).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [EventStatus.APPROVED, EventStatus.CONFIRMED, EventStatus.CANCELLED]
)
def test_only_an_event_in_planning_can_be_confirmed(
    signed_in_coordinator, organiser, coordinator, hall, status
):
    event = make_event(organiser, status=status, coordinator=coordinator)
    book(event, hall)

    response = signed_in_coordinator.post(url(event))

    assert response.status_code == 409
