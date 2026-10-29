from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.equipment.contracts import lock_equipment_types, validate_period, validate_quantity
from apps.equipment.models import EquipmentType


@pytest.mark.parametrize("value", [1, 3, 1000])
def test_positive_whole_quantity_contract(value):
    validate_quantity(value)


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "3", None])
def test_invalid_quantity_contract(value):
    with pytest.raises(ValidationError, match="positive whole"):
        validate_quantity(value)


def test_aware_positive_period_contract():
    start = datetime(2027, 3, 1, 2, tzinfo=UTC)
    validate_period(start, start + timedelta(seconds=1))


@pytest.mark.parametrize(
    "case",
    ["missing_start", "missing_end", "string", "naive_start", "naive_end", "equal", "reversed"],
)
def test_invalid_period_contract(case):
    start = datetime(2027, 3, 1, 2, tzinfo=UTC)
    end = start + timedelta(hours=2)
    if case == "missing_start":
        start = None
    elif case == "missing_end":
        end = None
    elif case == "string":
        start = "2027-03-01"
    elif case == "naive_start":
        start = start.replace(tzinfo=None)
    elif case == "naive_end":
        end = end.replace(tzinfo=None)
    elif case == "equal":
        end = start
    else:
        end = start - timedelta(seconds=1)
    with pytest.raises(ValidationError):
        validate_period(start, end)


@pytest.mark.django_db
def test_lock_types_orders_and_deduplicates(stock):
    other = EquipmentType.objects.create(code="MIC", name="Microphone", total_quantity=2)
    assert [row.pk for row in lock_equipment_types([other.pk, stock.pk, other.pk])] == [
        stock.pk,
        other.pk,
    ]
    assert lock_equipment_types([]) == []


@pytest.mark.django_db
@pytest.mark.parametrize("ids", [[0], [-1], ["1"], [True], [1, True], [None], [1.5], [999999]])
def test_invalid_or_missing_type_ids(ids):
    with pytest.raises(ValidationError):
        lock_equipment_types(ids)


@pytest.mark.django_db(transaction=True)
def test_lock_requires_callers_transaction(stock):
    with pytest.raises(transaction.TransactionManagementError):
        lock_equipment_types([stock.pk])
