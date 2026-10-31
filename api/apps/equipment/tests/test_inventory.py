from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.utils import timezone

from apps.equipment.contracts import lock_equipment_types
from apps.equipment.inventory import (
    restore_unavailability,
    save_equipment_type,
    save_unavailability,
)
from apps.equipment.models import EquipmentType, EquipmentUnavailability, UnavailabilityCause

pytestmark = pytest.mark.django_db


def unavailable(stock, tech, quantity=1, **kwargs):
    return EquipmentUnavailability(
        equipment_type=stock,
        quantity=quantity,
        cause=UnavailabilityCause.DAMAGED,
        reason=" Lens cracked ",
        reported_by=tech,
        **kwargs,
    )


def test_stock_counts_damage_and_maintenance_without_auto_restoring_expired_estimate(stock, tech):
    damaged = save_unavailability(
        unavailable(stock, tech, expected_return_at=timezone.now() - timezone.timedelta(days=1))
    )
    maintenance = unavailable(stock, tech)
    maintenance.cause = UnavailabilityCause.MAINTENANCE
    save_unavailability(maintenance)
    stock.refresh_from_db()
    assert stock.total_quantity == 10
    assert stock.unavailable_quantity == 2
    assert stock.total_quantity - stock.unavailable_quantity == 8
    damaged.refresh_from_db()
    assert damaged.reason == "Lens cracked" and damaged.restored_at is None
    assert damaged.reported_by == tech


def test_new_empty_stock_and_valid_stock_update():
    item = EquipmentType(code="NEW", name="New type", total_quantity=0)
    assert item.unavailable_quantity == 0
    save_equipment_type(item)
    item.total_quantity = 5
    save_equipment_type(item)
    item.refresh_from_db()
    assert item.total_quantity == 5 and item.unavailable_quantity == 0


def test_total_can_equal_unavailable_but_cannot_be_below_it(stock, tech):
    save_unavailability(unavailable(stock, tech, 2))
    stock.total_quantity = 2
    save_equipment_type(stock)
    stock.total_quantity = 1
    with pytest.raises(ValidationError, match="below recorded unavailable"):
        save_equipment_type(stock)
    stock.refresh_from_db()
    assert stock.total_quantity == stock.unavailable_quantity == 2


def test_unavailable_total_rechecked_against_fresh_locked_stock(stock, tech):
    # The caller's cached type still says 10; the database now contains only 1.
    EquipmentType.objects.filter(pk=stock.pk).update(total_quantity=1)
    record = unavailable(stock, tech, 2)
    with pytest.raises(ValidationError, match="cannot exceed"):
        save_unavailability(record)
    assert not EquipmentUnavailability.objects.exists()


def test_updating_existing_record_excludes_its_own_quantity(stock, tech):
    record = save_unavailability(unavailable(stock, tech, 6))
    record.quantity = 10
    save_unavailability(record)
    record.refresh_from_db()
    assert record.quantity == stock.unavailable_quantity == 10


@pytest.mark.parametrize("quantity", [0, -1, 11])
def test_invalid_unavailable_quantity_has_no_partial_write(stock, tech, quantity):
    with pytest.raises(ValidationError):
        save_unavailability(unavailable(stock, tech, quantity))
    assert not EquipmentUnavailability.objects.exists()


@pytest.mark.parametrize("reason", ["", "   ", None, 12])
def test_reason_required(stock, tech, reason):
    record = unavailable(stock, tech)
    record.reason = reason
    with pytest.raises(ValidationError):
        save_unavailability(record)
    assert not EquipmentUnavailability.objects.exists()


def test_naive_return_estimate_refused(stock, tech):
    with pytest.raises(ValidationError, match="timezone-aware"):
        save_unavailability(unavailable(stock, tech, expected_return_at=datetime(2027, 3, 1)))
    assert not EquipmentUnavailability.objects.exists()


def test_record_cannot_move_type_or_be_edited_after_restore(stock, tech):
    record = save_unavailability(unavailable(stock, tech))
    other = EquipmentType.objects.create(code="OTHER", name="Other", total_quantity=10)
    record.equipment_type = other
    with pytest.raises(ValidationError, match="cannot change"):
        save_unavailability(record)
    record.refresh_from_db()
    restore_unavailability(record, tech)
    record.reason = "Rewrite history"
    with pytest.raises(ValidationError, match="cannot be edited"):
        save_unavailability(record)


def test_restore_retains_record_actor_time_and_is_idempotent(stock, tech):
    record = save_unavailability(unavailable(stock, tech, 2))
    restore_unavailability(record, tech)
    first_time = record.restored_at
    restore_unavailability(record, tech)
    record.refresh_from_db()
    assert record.restored_by == tech and record.restored_at == first_time
    assert record.quantity == 2 and record.reason == "Lens cracked"
    assert stock.unavailable_quantity == 0 and stock.total_quantity == 10
    assert EquipmentUnavailability.objects.count() == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": 0},
        {"quantity": -1},
        {"cause": "UNKNOWN"},
        {"reason": " \t\n"},
        {"restored_at": timezone.now()},
        {"restored_by": True},
    ],
)
def test_database_refuses_invalid_unavailability_records(stock, tech, changes):
    data = {
        "equipment_type": stock,
        "quantity": 1,
        "cause": "DAMAGED",
        "reason": "Broken",
        "reported_by": tech,
    }
    if changes.get("restored_by"):
        changes = {"restored_by": tech}
    data.update(changes)
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentUnavailability.objects.create(**data)


@pytest.mark.django_db(transaction=True)
def test_concurrent_unavailability_cannot_exceed_stock(stock, tech):
    barrier = Barrier(2)

    def attempt(_):
        close_old_connections()
        try:
            item = EquipmentType.objects.get(pk=stock.pk)
            record = unavailable(item, tech, 6)
            barrier.wait(timeout=10)
            try:
                save_unavailability(record)
                return "saved"
            except ValidationError:
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["refused", "saved"]
    assert stock.unavailable_quantity == 6
    assert EquipmentUnavailability.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_stock_reduction_and_new_unavailability_serialize(stock, tech):
    save_unavailability(unavailable(stock, tech, 6))
    barrier = Barrier(2)

    def attempt(reduce_stock):
        close_old_connections()
        try:
            item = EquipmentType.objects.get(pk=stock.pk)
            barrier.wait(timeout=10)
            try:
                if reduce_stock:
                    item.total_quantity = 6
                    save_equipment_type(item)
                else:
                    save_unavailability(unavailable(item, tech, 4))
                return "saved"
            except ValidationError:
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [True, False]))
    assert sorted(results) == ["refused", "saved"]
    stock.refresh_from_db()
    assert (stock.total_quantity, stock.unavailable_quantity) in {(6, 6), (10, 10)}


@pytest.mark.django_db(transaction=True)
def test_type_lock_is_held_until_callers_transaction_ends(stock):
    def competing_lock():
        close_old_connections()
        try:
            with transaction.atomic():
                EquipmentType.objects.select_for_update(nowait=True).get(pk=stock.pk)
        finally:
            close_old_connections()

    with transaction.atomic():
        lock_equipment_types([stock.pk])
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(OperationalError):
                pool.submit(competing_lock).result(timeout=10)
