"""SCRUM-12 - As Technical Support Staff, I want to check whether there is sufficient
suitable equipment available for the event period, so that unavailable or
insufficient equipment is not promised.

Sprint 3 gate G15. Each test is named after the acceptance criterion it verifies;
case IDs are in docs/test-cases/S3-SCRUM-12-equipment-availability.csv.

Reservations are created directly on the G03 models: the SCRUM-16 reservation
action (G16a) and SCRUM-75 amendment (G17) do not exist yet. The guide asks for
the quantity cases to be rerun through those real actions once they merge.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailability,
    UnavailabilityCause,
)
from apps.equipment.services import (
    AvailabilityStatus,
    availability_row,
    available_quantity,
    reserved_quantity,
)
from conftest import _make_user, make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime(2026, 12, 1, 10, 0, tzinfo=SGT)
END = datetime(2026, 12, 1, 12, 0, tzinfo=SGT)


@pytest.fixture
def projector(db):
    return EquipmentType.objects.create(code="PROJECTOR", name="Projector", total_quantity=10)


@pytest.fixture
def event(organiser, coordinator):
    """An event in planning, assigned to the coordinator, on 1 Dec 10:00-12:00."""
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=START,
        preferred_end=END,
    )


def other_event(organiser, name="Other event", status=EventStatus.PLANNING):
    return make_event(organiser, status=status, name=name, preferred_start=START, preferred_end=END)


def request_for(event, equipment_type, quantity, user):
    plan, _ = EquipmentPlan.objects.get_or_create(event=event)
    return EquipmentRequest.objects.create(
        plan=plan, equipment_type=equipment_type, quantity=quantity, requested_by=user
    )


def reserve(event, equipment_type, quantity, tech, start=START, end=END):
    """A reservation row as the G16a action will create it."""
    item = request_for(event, equipment_type, quantity, event.created_by)
    item.status = EquipmentRequestStatus.RESERVED
    item.save(update_fields=["status"])
    return EquipmentReservation.objects.create(
        request=item, quantity=quantity, starts_at=start, ends_at=end, reserved_by=tech
    )


def out_of_action(equipment_type, quantity, tech, cause=UnavailabilityCause.DAMAGED, **extra):
    return EquipmentUnavailability.objects.create(
        equipment_type=equipment_type,
        quantity=quantity,
        cause=cause,
        reason=extra.pop("reason", "Lens cracked"),
        reported_by=tech,
        **extra,
    )


def url(event, query=""):
    return f"/api/events/{event.pk}/equipment-availability/{query}"


# AC1/AC2 - the available quantity for the period --------------------------------


@pytest.mark.django_db
def test_ac2_total_10_unavailable_2_reserved_5_leaves_3(organiser, projector, tech):
    """S3-12-01: 10 - 2 damaged - 5 reserved by another event = 3."""
    out_of_action(projector, 2, tech)
    reserve(other_event(organiser), projector, 5, tech)

    assert available_quantity(projector, START, END) == 3
    row = availability_row(projector, START, END)
    assert (row["total_quantity"], row["unavailable_quantity"]) == (10, 2)
    assert row["reserved_for_other_events"] == 5
    assert row["available_quantity"] == 3
    assert row["status"] == AvailabilityStatus.PARTIAL


@pytest.mark.django_db
def test_ac2_with_nothing_reserved_or_damaged_everything_is_available(projector):
    row = availability_row(projector, START, END)

    assert row["available_quantity"] == 10
    assert row["status"] == AvailabilityStatus.AVAILABLE


@pytest.mark.django_db
def test_ac2_reservations_of_several_events_add_up(organiser, projector, tech):
    reserve(other_event(organiser, "A"), projector, 3, tech)
    reserve(other_event(organiser, "B"), projector, 4, tech)

    assert reserved_quantity(projector, START, END) == 7
    assert available_quantity(projector, START, END) == 3


@pytest.mark.django_db
def test_ac2_other_equipment_types_do_not_affect_the_count(organiser, projector, tech):
    mic = EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=4)
    reserve(other_event(organiser), mic, 4, tech)

    assert available_quantity(projector, START, END) == 10
    assert available_quantity(mic, START, END) == 0


# AC3 - reserved for another event during the period ------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end", "available"),
    [
        (START - timedelta(hours=2), START, 10),
        (END, END + timedelta(hours=1), 10),
        (START - timedelta(hours=2), START + timedelta(seconds=1), 4),
        (END - timedelta(seconds=1), END + timedelta(hours=1), 4),
        (START + timedelta(minutes=30), END - timedelta(minutes=30), 4),
    ],
    ids=[
        "ends-exactly-at-start",
        "starts-exactly-at-end",
        "one-second-overlap-at-start",
        "one-second-overlap-at-end",
        "inside",
    ],
)
def test_ac3_only_overlapping_reservations_reduce_the_period(
    organiser, projector, tech, start, end, available
):
    """S3-12-02: half-open periods; adjacency does not overlap."""
    reserve(other_event(organiser), projector, 6, tech, start=start, end=end)

    assert available_quantity(projector, START, END) == available


@pytest.mark.django_db
def test_ac3_fully_reserved_equipment_is_shown_as_unavailable(organiser, projector, tech):
    reserve(other_event(organiser), projector, 10, tech)

    row = availability_row(projector, START, END)

    assert row["available_quantity"] == 0
    assert row["status"] == AvailabilityStatus.UNAVAILABLE


@pytest.mark.django_db
def test_ac3_released_reservations_and_cancelled_events_do_not_count(organiser, projector, tech):
    released = reserve(other_event(organiser, "Released"), projector, 3, tech)
    released.status = "RELEASED"
    released.released_by = tech
    released.released_at = timezone.now()
    released.release_reason = "Event scaled down"
    released.save()
    reserve(other_event(organiser, "Cancelled", EventStatus.CANCELLED), projector, 4, tech)

    assert available_quantity(projector, START, END) == 10


@pytest.mark.django_db
def test_ac3_an_events_own_reservation_is_not_unavailable_to_it(event, organiser, projector, tech):
    reserve(event, projector, 4, tech)
    reserve(other_event(organiser), projector, 3, tech)

    row = availability_row(projector, START, END, requested=4, event=event)

    assert row["reserved_for_this_event"] == 4
    assert row["reserved_for_other_events"] == 3
    assert row["available_quantity"] == 7
    assert row["shortfall"] == 0


# AC4 - damaged or under maintenance -------------------------------------------------


@pytest.mark.django_db
def test_ac4_damaged_and_maintenance_stock_is_unavailable_for_any_period(projector, tech):
    """S3-12-03: unavailable regardless of the period, with reason and return date."""
    back = datetime(2026, 12, 20, 9, 0, tzinfo=SGT)
    out_of_action(projector, 1, tech, reason="Lens cracked")
    out_of_action(
        projector,
        2,
        tech,
        cause=UnavailabilityCause.MAINTENANCE,
        reason="Lamp replacement",
        expected_return_at=back,
    )

    for start in (START, START + timedelta(days=365)):
        assert available_quantity(projector, start, start + timedelta(hours=1)) == 7
    row = availability_row(projector, START, END)
    assert row["unavailable_quantity"] == 3
    assert row["unavailable"] == [
        {
            "quantity": 1,
            "cause": "DAMAGED",
            "cause_label": "Damaged",
            "reason": "Lens cracked",
            "expected_return_at": None,
        },
        {
            "quantity": 2,
            "cause": "MAINTENANCE",
            "cause_label": "Under maintenance",
            "reason": "Lamp replacement",
            "expected_return_at": back,
        },
    ]


@pytest.mark.django_db
def test_ac4_restored_stock_counts_again(projector, tech):
    record = out_of_action(projector, 2, tech)
    record.restored_by = tech
    record.restored_at = timezone.now()
    record.save()

    row = availability_row(projector, START, END)

    assert row["available_quantity"] == 10
    assert row["unavailable"] == []


@pytest.mark.django_db
def test_ac4_damaged_stock_and_reservations_never_go_below_zero(organiser, projector, tech):
    out_of_action(projector, 6, tech)
    reserve(other_event(organiser), projector, 8, tech)

    assert available_quantity(projector, START, END) == 0


@pytest.mark.django_db
def test_ac4_a_type_no_longer_offered_has_none_available(projector):
    projector.in_service = False
    projector.save(update_fields=["in_service"])

    row = availability_row(projector, START, END, requested=1)

    assert row["available_quantity"] == 0
    assert row["status"] == AvailabilityStatus.UNAVAILABLE
    assert row["in_service"] is False


# AC5 - shortfall ----------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("requested", "shortfall"), [(2, 0), (3, 0), (4, 1), (9, 6)], ids=["2", "3", "4", "9"]
)
def test_ac5_the_shortfall_is_what_cannot_be_supplied(
    organiser, projector, tech, requested, shortfall
):
    """S3-12-04: 3 available; requesting 4 is short by 1."""
    out_of_action(projector, 2, tech)
    reserve(other_event(organiser), projector, 5, tech)

    row = availability_row(projector, START, END, requested=requested)

    assert row["requested_quantity"] == requested
    assert row["shortfall"] == shortfall


@pytest.mark.django_db
def test_period_must_be_aware_and_positive(projector):
    with pytest.raises(ValidationError):
        available_quantity(projector, END, START)
    with pytest.raises(ValidationError):
        availability_row(projector, START.replace(tzinfo=None), END.replace(tzinfo=None))


# API - AC1 to AC5 through the screen's endpoint ------------------------------------


@pytest.mark.django_db
def test_ac1_api_the_assigned_coordinator_sees_every_type_for_the_event_period(
    api, event, coordinator, organiser, projector, tech
):
    EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=4)
    EquipmentType.objects.create(code="OLD", name="Old screen", total_quantity=2, in_service=False)
    request_for(event, projector, 4, coordinator)
    out_of_action(projector, 2, tech)
    reserve(other_event(organiser), projector, 5, tech)
    api.force_authenticate(coordinator)

    response = api.get(url(event))

    assert response.status_code == 200
    assert response.data["event"]["id"] == event.pk
    assert response.data["period"] == {"starts_at": START, "ends_at": END}
    names = [row["name"] for row in response.data["equipment"]]
    assert names == ["Microphone", "Projector"]  # retired, unrequested type left out
    projector_row = response.data["equipment"][1]
    assert projector_row["available_quantity"] == 3
    assert projector_row["shortfall"] == 1
    assert response.data["shortfalls"] == [{"name": "Projector", "requested": 4, "short_by": 1}]


@pytest.mark.django_db
def test_ac1_api_technical_support_choose_another_period(
    api, event, coordinator, organiser, projector, tech
):
    request_for(event, projector, 2, coordinator)
    reserve(other_event(organiser), projector, 9, tech)
    api.force_authenticate(tech)
    later = START + timedelta(days=1)

    response = api.get(
        url(event),
        {"starts_at": later.isoformat(), "ends_at": (later + timedelta(hours=2)).isoformat()},
    )

    assert response.status_code == 200
    assert response.data["period"]["starts_at"] == later
    assert response.data["equipment"][0]["available_quantity"] == 10


@pytest.mark.django_db
def test_api_a_retired_type_still_requested_is_listed_as_unavailable(
    api, event, coordinator, projector
):
    request_for(event, projector, 2, coordinator)
    projector.in_service = False
    projector.save(update_fields=["in_service"])
    api.force_authenticate(coordinator)

    (row,) = api.get(url(event)).data["equipment"]

    assert (row["name"], row["available_quantity"], row["shortfall"]) == ("Projector", 0, 2)


@pytest.mark.django_db
def test_api_withdrawn_requests_are_not_counted_as_requested(api, event, coordinator, projector):
    item = request_for(event, projector, 12, coordinator)
    item.status = EquipmentRequestStatus.WITHDRAWN
    item.save(update_fields=["status"])
    api.force_authenticate(coordinator)

    data = api.get(url(event)).data

    assert data["equipment"][0]["requested_quantity"] is None
    assert data["shortfalls"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"starts_at": "2026-12-01T10:00:00+08:00"}, "Give both a start and an end, or neither."),
        (
            {"starts_at": "tomorrow", "ends_at": "later"},
            "Use ISO 8601 date-times with a time zone.",
        ),
        (
            {"starts_at": "2026-12-41T10:00:00+08:00", "ends_at": "2026-12-41T12:00:00+08:00"},
            "Use ISO 8601 date-times with a time zone.",
        ),
        (
            {"starts_at": "2026-12-01T10:00:00", "ends_at": "2026-12-01T12:00:00"},
            "Use timezone-aware equipment periods.",
        ),
        (
            {"starts_at": "2026-12-01T12:00:00+08:00", "ends_at": "2026-12-01T10:00:00+08:00"},
            "End must be after start.",
        ),
    ],
    ids=["one-end-only", "not-a-date", "impossible-date", "no-time-zone", "reversed"],
)
def test_api_an_invalid_period_is_refused(api, event, coordinator, query, message):
    api.force_authenticate(coordinator)

    response = api.get(url(event), query)

    assert response.status_code == 400
    assert response.data["period"] == [message]


@pytest.mark.django_db
def test_api_an_event_without_dates_needs_a_period(api, organiser, coordinator):
    undated = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        preferred_start=None,
        preferred_end=None,
    )
    api.force_authenticate(coordinator)

    response = api.get(url(undated))

    assert response.status_code == 400
    assert response.data["period"] == ["This event has no dates yet; choose a period."]


@pytest.mark.django_db
def test_api_the_check_changes_nothing(api, event, coordinator, organiser, projector, tech):
    reservation = reserve(other_event(organiser), projector, 5, tech)
    api.force_authenticate(coordinator)
    before = (projector.updated_at, reservation.updated_at, EquipmentReservation.objects.count())

    api.get(url(event))

    projector.refresh_from_db()
    reservation.refresh_from_db()
    assert (
        projector.updated_at,
        reservation.updated_at,
        EquipmentReservation.objects.count(),
    ) == before


# API - AC6 who may check -------------------------------------------------------------


@pytest.mark.django_db
def test_ac6_technical_support_may_check_an_event_with_equipment_requested(
    api, event, coordinator, projector, tech
):
    request_for(event, projector, 1, coordinator)
    api.force_authenticate(tech)

    assert api.get(url(event)).status_code == 200


@pytest.mark.django_db
def test_ac6_technical_support_are_refused_an_event_with_no_equipment(api, event, tech):
    api.force_authenticate(tech)

    assert api.get(url(event)).status_code == 403
    assert AuditLog.objects.get(actor=tech, allowed=False).detail == (
        "no equipment has been requested for this event"
    )


@pytest.mark.django_db
def test_ac6_another_or_reassigned_coordinator_is_refused_and_audited(
    api, event, second_coordinator
):
    api.force_authenticate(second_coordinator)

    assert api.get(url(event)).status_code == 403
    assert AuditLog.objects.get(actor=second_coordinator, allowed=False).detail == (
        "coordinator is not assigned to this event"
    )


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
def test_ac6_other_roles_are_refused_and_audited_without_holding_details(
    api, event, organiser, projector, tech, acme, role
):
    """S3-12-05: the refusal reveals no reservation or holding-event detail."""
    reserve(other_event(organiser, "Confidential launch"), projector, 5, tech)
    user = _make_user(f"{role.lower()}@x.example", role, acme)
    api.force_authenticate(user)

    response = api.get(url(event))

    assert response.status_code == 403
    assert set(response.data) == {"detail"}
    assert "Confidential launch" not in str(response.data)
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_ac6_a_draft_is_refused(api, organiser, coordinator):
    draft = make_event(organiser, status=EventStatus.DRAFT, coordinator=coordinator)
    api.force_authenticate(coordinator)

    assert api.get(url(draft)).status_code == 403


@pytest.mark.django_db
def test_ac6_anonymous_callers_are_refused_and_recorded(api, event):
    assert api.get(url(event)).status_code in (401, 403)
    assert AuditLog.objects.filter(actor=None, allowed=False).exists()


@pytest.mark.django_db
def test_api_an_unknown_event_is_not_found(api, coordinator):
    api.force_authenticate(coordinator)

    assert api.get("/api/events/999999/equipment-availability/").status_code == 404
