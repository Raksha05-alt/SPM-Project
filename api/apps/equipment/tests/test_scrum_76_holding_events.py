"""SCRUM-76 - As Technical Support Staff, I want to see which events are holding the
equipment an event needs, so that I can negotiate rather than simply reporting that
nothing is available.

Sprint 3 gate G18. Reservations are made through the real SCRUM-16 reserve
endpoint and released through the real SCRUM-77 / INT-03 cancellation endpoint.
Case IDs are in docs/test-cases/S3-SCRUM-76-holding-events.csv.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentType, EquipmentUnavailability, UnavailabilityCause
from apps.equipment.services import create_request, holders, holding_reservations
from conftest import _make_user, make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime(2026, 12, 1, 10, 0, tzinfo=SGT)
END = datetime(2026, 12, 1, 12, 0, tzinfo=SGT)


@pytest.fixture
def projector(db):
    return EquipmentType.objects.create(code="PROJECTOR", name="Projector", total_quantity=10)


@pytest.fixture
def event(organiser, coordinator):
    """The event that needs the equipment, assigned to ``coordinator``."""
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        name="Partner Summit",
        coordinator=coordinator,
        preferred_start=START,
        preferred_end=END,
    )


def holding_event(organiser, coordinator, name, start=START, end=END):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        name=name,
        coordinator=coordinator,
        preferred_start=start,
        preferred_end=end,
    )


def reserve_for(event, equipment_type, quantity, tech):
    """Request as the event's coordinator, then reserve through the real endpoint."""
    item = create_request(
        event=event,
        requested_by=event.coordinator,
        equipment_type=equipment_type.pk,
        quantity=quantity,
    )
    client = APIClient()
    client.force_authenticate(tech)
    response = client.post(
        f"/api/equipment/requests/{item.pk}/reserve/",
        {"expected_revision": item.plan.revision},
        format="json",
    )
    assert response.status_code == 200, response.data
    return item


def cancel(event):
    client = APIClient()
    client.force_authenticate(event.coordinator)
    preview = client.get(f"/api/events/{event.pk}/cancellation-preview/")
    response = client.post(
        f"/api/events/{event.pk}/cancel/",
        {
            "expected_version": preview.data["version"],
            "confirm_cancel": True,
            "reason": "Client cancelled the event.",
        },
        format="json",
    )
    assert response.status_code == 200, response.data


def url(event, equipment_type, query=""):
    return f"/api/events/{event.pk}/equipment-availability/{equipment_type.pk}/{query}"


@pytest.fixture
def held(organiser, second_coordinator, projector, tech):
    """Two other events holding 3 and 4 projectors over the same period."""
    early = holding_event(
        organiser, second_coordinator, "Board Offsite", START - timedelta(hours=1), END
    )
    late = holding_event(
        organiser, second_coordinator, "Product Launch", START, END + timedelta(hours=1)
    )
    reserve_for(early, projector, 3, tech)
    reserve_for(late, projector, 4, tech)
    return early, late


# AC1 - the events holding reserved equipment, with their dates -----------------------


@pytest.mark.django_db
def test_ac1_technical_support_see_each_holding_event_and_its_dates(
    api, event, coordinator, projector, tech, held, second_coordinator
):
    """S3-76-01: real overlapping reservations identify the holding events and dates."""
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=5)
    early, late = held
    api.force_authenticate(tech)

    response = api.get(url(event, projector))

    assert response.status_code == 200
    assert response.data["availability"]["available_quantity"] == 3
    assert response.data["availability"]["shortfall"] == 2
    assert [
        (h["event"]["name"], h["quantity"], h["starts_at"], h["ends_at"])
        for h in response.data["holders"]
    ] == [
        ("Board Offsite", 3, START - timedelta(hours=1), END),
        ("Product Launch", 4, START, END + timedelta(hours=1)),
    ]
    first = response.data["holders"][0]["event"]
    assert first["id"] == early.pk
    assert first["status_label"] == "Planning"
    assert first["coordinator"] == {
        "name": "Casey Coordinator",
        "email": second_coordinator.email,
    }


@pytest.mark.django_db
def test_ac1_only_reservations_overlapping_the_period_are_listed(
    organiser, second_coordinator, projector, tech
):
    before = holding_event(
        organiser, second_coordinator, "Breakfast", START - timedelta(hours=2), START
    )
    after = holding_event(organiser, second_coordinator, "Dinner", END, END + timedelta(hours=2))
    overlapping = holding_event(
        organiser,
        second_coordinator,
        "Briefing",
        END - timedelta(seconds=1),
        END + timedelta(hours=1),
    )
    for e in (before, after, overlapping):
        reserve_for(e, projector, 2, tech)

    assert [r.request.plan.event.name for r in holding_reservations(projector, START, END)] == [
        "Briefing"
    ]


@pytest.mark.django_db
def test_ac1_the_events_own_reservation_is_not_listed_as_a_holder(
    api, event, coordinator, projector, tech, held
):
    reserve_for(event, projector, 2, tech)
    api.force_authenticate(tech)

    names = [h["event"]["name"] for h in api.get(url(event, projector)).data["holders"]]

    assert names == ["Board Offsite", "Product Launch"]


@pytest.mark.django_db
def test_ac1_other_equipment_types_and_no_holders(api, event, coordinator, projector, tech, held):
    mic = EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=4)
    create_request(event=event, requested_by=coordinator, equipment_type=mic.pk, quantity=1)
    api.force_authenticate(tech)

    data = api.get(url(event, mic)).data

    assert data["holders"] == []
    assert data["availability"]["available_quantity"] == 4


# AC2 - damaged or under maintenance -----------------------------------------------------


@pytest.mark.django_db
def test_ac2_reason_and_expected_return_are_shown_where_recorded(
    api, event, coordinator, projector, tech
):
    """S3-76-02: the reason and return date display; an unknown return is explicit."""
    back = datetime(2026, 12, 20, 9, 0, tzinfo=SGT)
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=1)
    EquipmentUnavailability.objects.create(
        equipment_type=projector,
        quantity=2,
        cause=UnavailabilityCause.MAINTENANCE,
        reason="Lamp replacement",
        expected_return_at=back,
        reported_by=tech,
    )
    EquipmentUnavailability.objects.create(
        equipment_type=projector,
        quantity=1,
        cause=UnavailabilityCause.DAMAGED,
        reason="Lens cracked",
        reported_by=tech,
    )
    api.force_authenticate(tech)

    unavailable = api.get(url(event, projector)).data["availability"]["unavailable"]

    assert [(u["cause_label"], u["reason"], u["expected_return_at"]) for u in unavailable] == [
        ("Under maintenance", "Lamp replacement", back),
        ("Damaged", "Lens cracked", None),
    ]


# AC3 - only what the viewer's role permits ------------------------------------------------


@pytest.mark.django_db
def test_ac3_the_assigned_coordinator_sees_quantity_and_dates_but_not_other_events(
    api, event, coordinator, projector, held
):
    """S3-76-03: role-scoped response through the API."""
    api.force_authenticate(coordinator)

    response = api.get(url(event, projector))

    assert response.status_code == 200
    assert [(h["quantity"], h["starts_at"]) for h in response.data["holders"]] == [
        (3, START - timedelta(hours=1)),
        (4, START),
    ]
    for entry in response.data["holders"]:
        assert set(entry) == {"reservation", "quantity", "starts_at", "ends_at"}
    body = str(response.data)
    assert "Board Offsite" not in body and "Product Launch" not in body
    assert "second@connectsphere.example" not in body


@pytest.mark.django_db
def test_ac3_technical_support_never_see_the_holding_clients_details(
    api, event, coordinator, projector, tech, held
):
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=1)
    api.force_authenticate(tech)

    holders_data = api.get(url(event, projector)).data["holders"]

    assert set(holders_data[0]) == {"reservation", "quantity", "starts_at", "ends_at", "event"}
    assert set(holders_data[0]["event"]) == {"id", "name", "status", "status_label", "coordinator"}
    assert "Acme" not in str(holders_data)


@pytest.mark.django_db
def test_ac3_the_service_scopes_by_role(event, coordinator, projector, tech, held):
    as_tech = holders(projector, START, END, viewer=tech, event=event)
    as_coordinator = holders(projector, START, END, viewer=coordinator, event=event)

    assert all("event" in h for h in as_tech)
    assert not any("event" in h for h in as_coordinator)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_COORDINATOR_LEAD,
        Role.EVENT_ORGANISER,
        Role.ATTENDEE,
        Role.VENUE_STAFF,
        Role.SAFETY_OFFICER,
    ],
)
def test_ac3_other_roles_are_refused_and_audited_without_holder_details(
    api, event, projector, held, acme, role
):
    user = _make_user(f"{role.lower()}@x.example", role, acme)
    api.force_authenticate(user)

    response = api.get(url(event, projector))

    assert response.status_code == 403
    assert set(response.data) == {"detail"}
    assert "Board Offsite" not in str(response.data)
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_ac3_another_coordinator_is_refused_and_audited(api, event, projector, held, acme):
    stranger = _make_user("stranger@connectsphere.example", Role.EVENT_COORDINATOR)
    api.force_authenticate(stranger)

    assert api.get(url(event, projector)).status_code == 403
    assert AuditLog.objects.get(actor=stranger, allowed=False).detail == (
        "coordinator is not assigned to this event"
    )


@pytest.mark.django_db
def test_ac3_technical_support_need_equipment_requested_on_the_event(api, event, projector, tech):
    api.force_authenticate(tech)

    assert api.get(url(event, projector)).status_code == 403


# AC4 - a cancelled holder releases the equipment ---------------------------------------


@pytest.mark.django_db
def test_ac4_cancelling_a_holding_event_makes_its_equipment_available_again(
    api, event, coordinator, projector, tech, held
):
    """S3-76-04: real cancellation; the next read shows the quantity free and the
    holder gone, while the other holder is preserved."""
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=5)
    early, late = held
    api.force_authenticate(tech)
    assert api.get(url(event, projector)).data["availability"]["available_quantity"] == 3

    cancel(early)

    api.force_authenticate(tech)
    data = api.get(url(event, projector)).data
    assert data["availability"]["available_quantity"] == 6
    assert data["availability"]["shortfall"] == 0
    assert [h["event"]["name"] for h in data["holders"]] == ["Product Launch"]
    summary = api.get(f"/api/events/{event.pk}/equipment-availability/").data
    assert summary["equipment"][0]["available_quantity"] == 6


@pytest.mark.django_db
def test_ac4_a_cancelled_event_never_holds_equipment_even_before_release(
    event, projector, tech, held
):
    """Defence in depth: a cancelled event's still-active reservation is ignored."""
    early, _ = held
    type(early).objects.filter(pk=early.pk).update(status=EventStatus.CANCELLED)

    assert [r.request.plan.event.name for r in holding_reservations(projector, START, END)] == [
        "Product Launch"
    ]


# Request handling ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_a_chosen_period_is_used(api, event, coordinator, projector, held, tech):
    create_request(event=event, requested_by=coordinator, equipment_type=projector.pk, quantity=1)
    api.force_authenticate(tech)
    later = START + timedelta(days=2)

    data = api.get(
        url(event, projector),
        {"starts_at": later.isoformat(), "ends_at": (later + timedelta(hours=1)).isoformat()},
    ).data

    assert data["period"]["starts_at"] == later
    assert data["holders"] == []


@pytest.mark.django_db
def test_api_an_invalid_period_is_refused(api, event, coordinator, projector):
    api.force_authenticate(coordinator)

    response = api.get(url(event, projector), {"starts_at": "2026-12-01T10:00:00+08:00"})

    assert response.status_code == 400
    assert response.data["period"] == ["Give both a start and an end, or neither."]


@pytest.mark.django_db
def test_api_an_unknown_event_or_equipment_type_is_not_found(api, event, coordinator):
    api.force_authenticate(coordinator)

    assert api.get(f"/api/events/{event.pk}/equipment-availability/999999/").status_code == 404
    assert api.get("/api/events/999999/equipment-availability/1/").status_code == 404


@pytest.mark.django_db
def test_ac1_a_holding_event_without_a_coordinator_is_still_listed(event, projector, tech, held):
    early, _ = held
    type(early).objects.filter(pk=early.pk).update(coordinator=None)

    as_tech = holders(projector, START, END, viewer=tech, event=event)

    assert [(h["event"]["name"], h["event"]["coordinator"]) for h in as_tech][0] == (
        "Board Offsite",
        None,
    )
