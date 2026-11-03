"""Sprint 3 final acceptance: fresh resources and reason validation.

Preconditions use the real venue, equipment and Safety services. The final
confirmation uses the public API; inventory changes use its real admin service.
"""

import pytest

from apps.equipment.inventory import save_equipment_type, save_unavailability
from apps.equipment.models import EquipmentReservation, EquipmentUnavailability
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification
from apps.safety.models import SafetyStatus
from apps.safety.services import decide, request_check
from apps.safety.tests.conftest import approve_equipment, approve_venue
from apps.safety.tests.conftest import planning_event as planning_event
from apps.safety.tests.conftest import safety_officer as safety_officer
from apps.safety.tests.conftest import tech as tech
from apps.safety.tests.conftest import venue as venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def accepted_plan(planning_event, venue, venue_staff, tech, coordinator, safety_officer):
    approve_venue(planning_event, venue, venue_staff)
    approve_equipment(planning_event, tech)
    decide(request_check(planning_event, coordinator), safety_officer, SafetyStatus.APPROVED)
    return planning_event


@pytest.mark.parametrize("change", ["retired", "damaged", "quantity", "period"])
def test_s3_final_01_current_equipment_must_still_cover_the_approved_plan(
    api, accepted_plan, coordinator, tech, change
):
    event = accepted_plan
    row = EquipmentReservation.objects.get(request__plan__event=event)
    stock = row.request.equipment_type
    if change == "retired":
        stock.in_service = False
        save_equipment_type(stock)
    elif change == "damaged":
        save_unavailability(
            EquipmentUnavailability(
                equipment_type=stock,
                quantity=9,
                cause="DAMAGED",
                reason="Damage recorded after reservation",
                reported_by=tech,
            )
        )
    elif change == "quantity":
        # Inconsistent resource snapshots must fail closed even if a producer
        # missed its invalidation hook; this is a fault-injection precondition.
        EquipmentReservation.objects.filter(pk=row.pk).update(quantity=1)
    else:
        EquipmentReservation.objects.filter(pk=row.pk).update(
            ends_at=event.preferred_end - (event.preferred_end - event.preferred_start) / 2
        )
    api.force_authenticate(coordinator)
    response = api.post(f"/api/events/{event.pk}/confirm/", {}, format="json")
    assert response.status_code == 409, response.data
    assert any("Equipment:" in gap for gap in response.data["missing"])
    event.refresh_from_db()
    assert event.status == "PLANNING" and event.confirmed_at is None
    assert not EventStatusHistory.objects.filter(event=event, to_status="CONFIRMED").exists()
    assert not Notification.objects.filter(event=event, kind="EVENT_CONFIRMED").exists()


@pytest.mark.parametrize("reason", [None, False, 17, {}, []])
def test_s3_final_02_unavailable_outcome_requires_a_real_text_reason(
    api, planning_event, coordinator, tech, reason
):
    from apps.equipment.models import EquipmentType
    from apps.equipment.services import create_request

    stock = EquipmentType.objects.create(
        code="FINAL-MIC", name="Final microphone", total_quantity=2
    )
    item = create_request(
        event=planning_event, requested_by=coordinator, equipment_type=stock.pk, quantity=1
    )
    api.force_authenticate(tech)
    response = api.post(
        f"/api/equipment/requests/{item.pk}/unavailable/", {"reason": reason}, format="json"
    )
    assert response.status_code == 400, response.data
    assert not item.history.filter(action="UNAVAILABLE").exists()
    assert not Notification.objects.filter(
        event=planning_event, kind="RESOURCE_UNAVAILABLE"
    ).exists()


def test_s3_final_03_real_event_cancellation_clears_a_conflict_for_staff_approval(
    api, planning_event, venue, venue_staff, coordinator, organiser
):
    from apps.core.statuses import EventStatus
    from apps.venues.bookings import request_booking
    from apps.venues.models import BookingStatus
    from conftest import make_event

    first = request_booking(
        event=planning_event,
        venue=venue,
        requested_by=coordinator,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=60,
        layout="THEATRE",
    )
    other = make_event(
        organiser,
        status=EventStatus.APPROVED,
        coordinator=coordinator,
        preferred_start=planning_event.preferred_start,
        preferred_end=planning_event.preferred_end,
        required_layout="THEATRE",
    )
    pending = request_booking(
        event=other,
        venue=venue,
        requested_by=coordinator,
        starts_at=other.preferred_start,
        ends_at=other.preferred_end,
        attendance=60,
        layout="THEATRE",
    )
    decision_url = f"/api/venue-bookings/{pending.pk}/approve/"
    api.force_authenticate(venue_staff)
    assert (
        api.post(f"/api/venue-bookings/{first.pk}/approve/", {}, format="json").status_code == 200
    )
    assert api.post(decision_url, {}, format="json").status_code == 409
    pending.refresh_from_db()
    assert pending.status == BookingStatus.PENDING
    api.force_authenticate(coordinator)
    preview = api.get(f"/api/events/{planning_event.pk}/cancellation-preview/")
    assert preview.status_code == 200
    cancelled = api.post(
        f"/api/events/{planning_event.pk}/cancel/",
        {
            "expected_version": preview.data["version"],
            "confirm_cancel": True,
            "reason": "Client cancelled.",
        },
        format="json",
    )
    assert cancelled.status_code == 200, cancelled.data
    planning_event.refresh_from_db()
    assert planning_event.status == EventStatus.CANCELLED
    assert planning_event.venue_bookings.get().status == BookingStatus.WITHDRAWN
    api.force_authenticate(venue_staff)
    response = api.post(decision_url, {}, format="json")
    assert response.status_code == 200, response.data
    pending.refresh_from_db()
    assert pending.status == BookingStatus.APPROVED
    assert pending.decided_by_id == venue_staff.pk and pending.decided_at is not None
