import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailability,
    ReservationStatus,
    TechnicalApproval,
    TechnicalApprovalStatus,
)
from conftest import make_event

pytestmark = pytest.mark.django_db


def reservation(request, tech, **overrides):
    event = request.plan.event
    data = {
        "request": request,
        "quantity": 5,
        "starts_at": event.preferred_start,
        "ends_at": event.preferred_end,
        "reserved_by": tech,
    }
    data.update(overrides)
    return EquipmentReservation(**data)


def test_request_persists_catalogue_identity_quantity_actor_and_text(
    equipment_request, coordinator, stock
):
    equipment_request.refresh_from_db()
    assert equipment_request.equipment_type == stock
    assert equipment_request.quantity == 8
    assert equipment_request.technical_requirements == "HDMI input; quiet fan"
    assert equipment_request.requested_by == coordinator
    assert equipment_request.requested_at is not None
    assert equipment_request.status == EquipmentRequestStatus.REQUESTED
    assert "quantity 8" in str(equipment_request)


@pytest.mark.parametrize("quantity", [0, -1])
def test_request_quantity_enforced_in_database(plan, stock, coordinator, quantity):
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentRequest.objects.create(
            plan=plan, equipment_type=stock, requested_by=coordinator, quantity=quantity
        )


def test_one_active_request_per_type_and_plan_with_retained_withdrawn_lines(
    equipment_request, coordinator
):
    data = {
        "plan": equipment_request.plan,
        "equipment_type": equipment_request.equipment_type,
        "requested_by": coordinator,
        "quantity": 3,
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentRequest.objects.create(**data)
    equipment_request.status = EquipmentRequestStatus.WITHDRAWN
    equipment_request.save()
    replacement = EquipmentRequest.objects.create(**data)
    assert replacement.pk != equipment_request.pk
    assert EquipmentRequest.objects.count() == 2
    assert EquipmentRequest.objects.get(pk=equipment_request.pk).quantity == 8


def test_plan_is_unique_per_event_and_revision_zero_is_valid(plan):
    plan.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentPlan.objects.create(event=plan.event)
    assert plan.revision == 0
    assert "revision 0" in str(plan)


def test_invalid_statuses_cannot_enter_database(equipment_request, tech):
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentRequest.objects.filter(pk=equipment_request.pk).update(status="INVALID")
    with pytest.raises(IntegrityError), transaction.atomic():
        reservation(equipment_request, tech, status="INVALID").save()
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentType.objects.create(code="BAD", name="Bad", total_quantity=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentPlan.objects.filter(pk=equipment_request.plan_id).update(revision=-1)


def test_reservation_stores_event_period_exact_quantity_and_staff(equipment_request, tech):
    record = reservation(equipment_request, tech)
    record.full_clean()
    record.save()
    record.refresh_from_db()
    assert record.quantity == 5
    assert record.starts_at == equipment_request.plan.event.preferred_start
    assert record.ends_at == equipment_request.plan.event.preferred_end
    assert record.reserved_by == tech and record.reserved_at is not None
    assert record.request_id == equipment_request.pk
    assert "ACTIVE" in str(record)


def test_reservation_cannot_exceed_request(equipment_request, tech):
    record = reservation(equipment_request, tech, quantity=9)
    with pytest.raises(ValidationError, match="cannot exceed"):
        record.full_clean()


@pytest.mark.parametrize(
    "case",
    [
        "zero_quantity",
        "negative_quantity",
        "equal_period",
        "reversed_period",
        "release_missing_user",
        "release_missing_time",
        "release_blank_reason",
        "active_has_release_data",
    ],
)
def test_database_reservation_constraints(equipment_request, tech, case):
    record = reservation(equipment_request, tech)
    if case == "zero_quantity":
        record.quantity = 0
    elif case == "negative_quantity":
        record.quantity = -1
    elif case == "equal_period":
        record.ends_at = record.starts_at
    elif case == "reversed_period":
        record.ends_at = record.starts_at - timezone.timedelta(seconds=1)
    else:
        record.status = ReservationStatus.RELEASED
        record.released_by = tech
        record.released_at = timezone.now()
        record.release_reason = "No longer required"
        if case == "release_missing_user":
            record.released_by = None
        elif case == "release_missing_time":
            record.released_at = None
        elif case == "release_blank_reason":
            record.release_reason = " \t\n"
        else:
            record.status = ReservationStatus.ACTIVE
    with pytest.raises(IntegrityError), transaction.atomic():
        record.save()


def test_only_one_active_reservation_but_released_history_can_repeat(equipment_request, tech):
    original = reservation(equipment_request, tech)
    original.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        reservation(equipment_request, tech, quantity=3).save()
    original.status = ReservationStatus.RELEASED
    original.released_by = tech
    original.released_at = timezone.now()
    original.release_reason = "Plan changed"
    original.full_clean()
    original.save()
    replacement = reservation(equipment_request, tech, quantity=3)
    replacement.save()
    original.refresh_from_db()
    assert original.quantity == 5 and original.release_reason == "Plan changed"
    assert original.released_by == tech and original.released_at is not None
    assert list(EquipmentReservation.objects.active()) == [replacement]


def test_half_open_overlap_and_cancelled_event_exclusion(
    equipment_request, tech, organiser, stock, coordinator
):
    record = reservation(equipment_request, tech)
    record.save()
    start, end = record.starts_at, record.ends_at
    assert list(EquipmentReservation.objects.active().overlapping(start, end)) == [record]
    assert (
        not EquipmentReservation.objects.active()
        .overlapping(end, end + timezone.timedelta(hours=1))
        .exists()
    )
    assert (
        not EquipmentReservation.objects.active()
        .overlapping(start - timezone.timedelta(hours=1), start)
        .exists()
    )
    assert list(
        EquipmentReservation.objects.active().overlapping(
            end - timezone.timedelta(seconds=1), end + timezone.timedelta(seconds=1)
        )
    ) == [record]
    cancelled = make_event(organiser, status=EventStatus.CANCELLED)
    other_plan = EquipmentPlan.objects.create(event=cancelled)
    other_request = EquipmentRequest.objects.create(
        plan=other_plan, equipment_type=stock, quantity=8, requested_by=coordinator
    )
    ignored = reservation(other_request, tech, starts_at=start, ends_at=end)
    ignored.save()
    assert not EquipmentReservation.objects.active().filter(pk=ignored.pk).exists()
    assert list(EquipmentReservation.objects.active().overlapping(start, end)) == [record]


def test_technical_approval_is_explicit_and_old_approval_is_retained(plan, tech):
    assert not plan.technical_approvals.exists()
    ambiguous = TechnicalApproval(plan=plan, plan_revision=0, approved_by=tech)
    with pytest.raises(ValidationError, match="Explicitly acknowledge"):
        ambiguous.full_clean()
    approval = TechnicalApproval(
        plan=plan, plan_revision=0, approved_by=tech, no_equipment_required=True
    )
    approval.full_clean()
    approval.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        TechnicalApproval.objects.create(
            plan=plan, plan_revision=0, approved_by=tech, no_equipment_required=True
        )
    approval.status = TechnicalApprovalStatus.SUPERSEDED
    approval.superseded_at = timezone.now()
    approval.full_clean()
    approval.save()
    plan.revision = 1
    plan.save()
    current = TechnicalApproval(
        plan=plan, plan_revision=1, approved_by=tech, no_equipment_required=True
    )
    current.full_clean()
    current.save()
    assert plan.technical_approvals.count() == 2
    assert approval.approved_by == tech and approval.approved_at is not None
    assert "revision 0" in str(approval)


def test_current_approval_rejects_stale_revision_or_false_no_equipment(equipment_request, tech):
    plan = equipment_request.plan
    stale = TechnicalApproval(plan=plan, plan_revision=1, approved_by=tech)
    with pytest.raises(ValidationError, match="current equipment revision"):
        stale.full_clean()
    false_empty = TechnicalApproval(
        plan=plan, plan_revision=0, approved_by=tech, no_equipment_required=True
    )
    with pytest.raises(ValidationError, match="still has equipment requests"):
        false_empty.full_clean()
    # Record validation is not the future technical-readiness workflow.
    valid_record = TechnicalApproval(plan=plan, plan_revision=0, approved_by=tech)
    valid_record.full_clean()


@pytest.mark.parametrize(
    "status,timestamp", [("APPROVED", True), ("SUPERSEDED", False), ("INVALID", False)]
)
def test_approval_state_timestamp_database_constraint(plan, tech, status, timestamp):
    with pytest.raises(IntegrityError), transaction.atomic():
        TechnicalApproval.objects.create(
            plan=plan,
            plan_revision=0,
            approved_by=tech,
            status=status,
            superseded_at=timezone.now() if timestamp else None,
        )


def test_history_snapshots_survive_future_request_changes(equipment_request, tech):
    record = reservation(equipment_request, tech)
    record.save()
    history = EquipmentHistory(
        plan=equipment_request.plan,
        request=equipment_request,
        reservation=record,
        action="AMENDED",
        plan_revision=0,
        before={"quantity": 5},
        after={"quantity": 3},
        actor=tech,
        reason="Two fewer projectors",
    )
    history.full_clean()
    history.save()
    equipment_request.quantity = 3
    equipment_request.save()
    history.refresh_from_db()
    assert history.before == {"quantity": 5} and history.after == {"quantity": 3}
    assert history.actor == tech and history.created_at is not None
    assert history.reason == "Two fewer projectors"
    assert "Amended" in str(history)
    with pytest.raises(ProtectedError):
        tech.delete()
    with pytest.raises(ProtectedError):
        equipment_request.plan.event.delete()
    with pytest.raises(ProtectedError):
        equipment_request.equipment_type.delete()
    with pytest.raises(ProtectedError):
        equipment_request.delete()
    with pytest.raises(ProtectedError):
        record.delete()


@pytest.mark.parametrize("snapshot", [None, [], "invalid"])
def test_history_requires_object_snapshots(plan, tech, snapshot):
    history = EquipmentHistory(
        plan=plan, action="APPROVED", plan_revision=0, actor=tech, before=snapshot
    )
    with pytest.raises(ValidationError, match="JSON objects"):
        history.full_clean()


def test_history_rejects_cross_plan_and_mismatched_reservation(
    equipment_request, tech, organiser, stock, coordinator
):
    other_plan = EquipmentPlan.objects.create(
        event=make_event(organiser, status=EventStatus.SUBMITTED)
    )
    other_req = EquipmentRequest.objects.create(
        plan=other_plan, equipment_type=stock, quantity=8, requested_by=coordinator
    )
    record = reservation(other_req, tech)
    record.save()
    history = EquipmentHistory(
        plan=equipment_request.plan,
        request=other_req,
        action="AMENDED",
        plan_revision=0,
        actor=tech,
    )
    with pytest.raises(ValidationError, match="request must belong"):
        history.full_clean()
    history.request = equipment_request
    history.reservation = record
    with pytest.raises(ValidationError, match="reservation must match"):
        history.full_clean()
    history.plan = other_plan
    with pytest.raises(ValidationError):
        history.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentHistory.objects.create(
            plan=other_plan, action="INVALID", plan_revision=0, actor=tech
        )


def test_unavailability_string(stock, tech):
    record = EquipmentUnavailability(
        equipment_type=stock, quantity=2, cause="DAMAGED", reason="Broken", reported_by=tech
    )
    assert str(record) == f"{stock.pk}: 2 Damaged"


def test_approval_validation_uses_fresh_plan_revision(plan, tech):
    approval = TechnicalApproval(
        plan=plan, plan_revision=0, approved_by=tech, no_equipment_required=True
    )
    EquipmentPlan.objects.filter(pk=plan.pk).update(revision=1)
    with pytest.raises(ValidationError, match="current equipment revision"):
        approval.full_clean()


def test_reservation_validation_uses_fresh_request_quantity(equipment_request, tech):
    record = reservation(equipment_request, tech, quantity=5)
    EquipmentRequest.objects.filter(pk=equipment_request.pk).update(quantity=3)
    with pytest.raises(ValidationError, match="cannot exceed"):
        record.full_clean()


@pytest.mark.parametrize(
    "model", ["unavailability", "reservation", "approval", "history_request", "history_reservation"]
)
def test_invalid_related_id_is_a_validation_error(equipment_request, tech, model):
    if model == "unavailability":
        record = EquipmentUnavailability(
            equipment_type_id=999999, quantity=1, cause="DAMAGED", reason="Broken", reported_by=tech
        )
    elif model == "reservation":
        record = reservation(equipment_request, tech)
        record.request_id = 999999
    elif model == "approval":
        record = TechnicalApproval(plan_id=999999, plan_revision=0, approved_by=tech)
    elif model == "history_request":
        record = EquipmentHistory(
            plan=equipment_request.plan,
            request_id=999999,
            action="AMENDED",
            plan_revision=0,
            actor=tech,
        )
    else:
        record = EquipmentHistory(
            plan=equipment_request.plan,
            reservation_id=999999,
            action="AMENDED",
            plan_revision=0,
            actor=tech,
        )
    with pytest.raises(ValidationError):
        record.full_clean()


def test_history_refuses_different_request_of_same_plan(
    equipment_request, stock, coordinator, tech
):
    other_type = EquipmentType.objects.create(code="SCREEN", name="Screen", total_quantity=4)
    other_request = EquipmentRequest.objects.create(
        plan=equipment_request.plan, equipment_type=other_type, quantity=4, requested_by=coordinator
    )
    record = reservation(other_request, tech, quantity=3)
    record.save()
    history = EquipmentHistory(
        plan=equipment_request.plan,
        request=equipment_request,
        reservation=record,
        action="RELEASED",
        plan_revision=0,
        actor=tech,
    )
    with pytest.raises(ValidationError, match="reservation must match"):
        history.full_clean()
