"""SCRUM-77 (US-17.2) - release reserved equipment."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequestStatus
from apps.equipment.services import available_quantity
from apps.equipment.tests.conftest import hold
from apps.notifications.models import Notification, NotificationKind


def url(reservation):
    return f"/api/equipment-reservations/{reservation.pk}/release/"


@pytest.mark.django_db
def test_ac1_cancelling_the_event_releases_its_reservations(
    signed_in_coordinator, event, projector
):
    reservation = hold(event, projector, 6)

    response = signed_in_coordinator.post(
        f"/api/events/{event.pk}/cancel/", {"reason": "Budget cut"}, format="json"
    )

    assert response.status_code == 200, response.data
    reservation.refresh_from_db()
    assert reservation.released_at is not None
    assert reservation.release_reason == "Event cancelled"
    assert available_quantity(projector, event.preferred_start, event.preferred_end) == 10


@pytest.mark.django_db
def test_ac2_a_manual_release_records_user_reason_and_time(
    signed_in_tech, tech_staff, coordinator, event, projector
):
    reservation = hold(event, projector, 4)

    response = signed_in_tech.post(url(reservation), {"reason": "Units recalled"}, format="json")

    assert response.status_code == 200, response.data
    reservation.refresh_from_db()
    assert (reservation.released_by, reservation.release_reason) == (tech_staff, "Units recalled")
    assert reservation.released_at is not None
    assert response.data["status"] == EquipmentRequestStatus.REQUESTED
    note = Notification.objects.get(recipient=coordinator)
    assert note.kind == NotificationKind.EQUIPMENT_RELEASED
    assert "Reason: Units recalled" in note.message


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"reason": "  "}])
def test_ac2_a_reason_is_required(signed_in_tech, event, projector, payload):
    reservation = hold(event, projector, 4)

    response = signed_in_tech.post(url(reservation), payload, format="json")

    assert response.status_code == 400
    reservation.refresh_from_db()
    assert reservation.released_at is None


@pytest.mark.django_db
def test_ac3_released_units_appear_as_available(signed_in_tech, event, projector):
    reservation = hold(event, projector, 4)
    signed_in_tech.post(url(reservation), {"reason": "Not needed"}, format="json")

    response = signed_in_tech.get(
        "/api/equipment/availability/",
        {"start": event.preferred_start.isoformat(), "end": event.preferred_end.isoformat()},
    )

    assert response.data["results"][0]["available_quantity"] == 10


@pytest.mark.django_db
def test_ac4_releasing_after_the_event_has_taken_place_is_refused(signed_in_tech, event, projector):
    past = timezone.now() - timezone.timedelta(days=2)
    reservation = hold(event, projector, 2, past, past + timezone.timedelta(hours=3))

    response = signed_in_tech.post(url(reservation), {"reason": "Tidy up"}, format="json")

    assert response.status_code == 409
    assert "already taken place" in response.data["detail"]


@pytest.mark.django_db
def test_ac4_a_completed_event_keeps_its_reservations(signed_in_tech, event, projector):
    reservation = hold(event, projector, 2)
    event.status = EventStatus.COMPLETED
    event.save()

    assert signed_in_tech.post(url(reservation), {"reason": "x"}, format="json").status_code == 409


@pytest.mark.django_db
def test_a_reservation_is_released_once(signed_in_tech, event, projector):
    reservation = hold(event, projector, 2)
    signed_in_tech.post(url(reservation), {"reason": "x"}, format="json")

    again = signed_in_tech.post(url(reservation), {"reason": "x"}, format="json")

    assert again.status_code == 409


@pytest.mark.django_db
def test_only_technical_staff_release_by_hand(signed_in_coordinator, event, projector):
    reservation = hold(event, projector, 2)

    assert (
        signed_in_coordinator.post(url(reservation), {"reason": "x"}, format="json").status_code
        == 403
    )
