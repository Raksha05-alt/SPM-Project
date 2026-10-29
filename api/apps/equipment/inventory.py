"""Catalogue maintenance only. Event resource actions are owned by later gates."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.equipment.contracts import lock_equipment_types
from apps.equipment.models import EquipmentUnavailability


@transaction.atomic
def save_equipment_type(instance):
    if instance.pk:
        lock_equipment_types([instance.pk])
    instance.full_clean()
    instance.save()
    return instance


@transaction.atomic
def save_unavailability(instance):
    equipment_type = lock_equipment_types([instance.equipment_type_id])[0]
    if instance.pk:
        previous = EquipmentUnavailability.objects.get(pk=instance.pk)
        if previous.equipment_type_id != equipment_type.pk:
            raise ValidationError("An unavailable-stock record cannot change equipment type.")
        if previous.restored_at is not None:
            raise ValidationError("Restored records are retained and cannot be edited.")
    # Drop any cached type instance so validation sees locked current stock.
    instance.equipment_type = equipment_type
    if not isinstance(instance.reason, str):
        raise ValidationError({"reason": "Record why this stock is unavailable."})
    instance.reason = instance.reason.strip()
    instance.full_clean()
    instance.save()
    return instance


@transaction.atomic
def restore_unavailability(record, actor):
    lock_equipment_types([record.equipment_type_id])
    current = EquipmentUnavailability.objects.get(pk=record.pk)
    if current.restored_at is not None:
        record.refresh_from_db()
        return record
    current.restored_by = actor
    current.restored_at = timezone.now()
    current.full_clean()
    current.save(update_fields=["restored_by", "restored_at", "updated_at"])
    record.refresh_from_db()
    return record
