"""Shared input and row-lock contracts; not reservation/availability workflows."""

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.equipment.models import EquipmentType


def validate_period(starts_at, ends_at):
    if not isinstance(starts_at, datetime) or not isinstance(ends_at, datetime):
        raise ValidationError("Provide both start and end as date-time values.")
    if timezone.is_naive(starts_at) or timezone.is_naive(ends_at):
        raise ValidationError("Use timezone-aware equipment periods.")
    if ends_at <= starts_at:
        raise ValidationError("End must be after start.")


def validate_quantity(quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValidationError("Equipment quantity must be a positive whole number.")


def lock_equipment_types(type_ids):
    """Call after the event lock (and venue locks) inside the caller's transaction."""
    if not connection.in_atomic_block:
        raise transaction.TransactionManagementError("Equipment locks require a transaction.")
    supplied = list(type_ids)
    if any(isinstance(pk, bool) or not isinstance(pk, int) or pk < 1 for pk in supplied):
        raise ValidationError("Equipment type IDs must be positive integers.")
    ids = set(supplied)
    rows = list(EquipmentType.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if {row.pk for row in rows} != ids:
        raise ValidationError("One or more equipment types do not exist.")
    return rows
