from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.equipment.admin import (
    EquipmentTypeAdmin,
    EquipmentUnavailabilityAdmin,
    ReadOnlyEquipmentAdmin,
)
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailability,
    TechnicalApproval,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def stock_admin(client, tech):
    tech.is_staff = True
    tech.is_superuser = True
    tech.save()
    client.force_login(tech)
    return client


def test_catalogue_admin_updates_stock_but_keeps_code_identity(stock_admin, stock):
    response = stock_admin.post(
        f"/admin/equipment/equipmenttype/{stock.pk}/change/",
        {
            "code": "FORGED",
            "name": "Projector renamed",
            "description": "Catalogue details",
            "total_quantity": "12",
            "in_service": "on",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    stock.refresh_from_db()
    assert stock.code == "PROJECTOR"
    assert stock.name == "Projector renamed" and stock.total_quantity == 12


def test_catalogue_admin_adds_type(stock_admin):
    response = stock_admin.post(
        "/admin/equipment/equipmenttype/add/",
        {
            "code": "SCREEN",
            "name": "Projection screen",
            "description": "",
            "total_quantity": "4",
            "in_service": "on",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    assert EquipmentType.objects.get(code="SCREEN").total_quantity == 4


def test_admin_handles_stock_conflict_without_server_error(stock_admin, stock):
    with patch(
        "apps.equipment.admin.save_equipment_type",
        side_effect=ValidationError("Stock changed; reload the catalogue."),
    ):
        response = stock_admin.post(
            f"/admin/equipment/equipmenttype/{stock.pk}/change/",
            {
                "name": "Projector",
                "description": "",
                "total_quantity": "8",
                "in_service": "on",
                "_save": "Save",
            },
            follow=True,
        )
    assert response.status_code == 200
    assert b"Stock changed; reload the catalogue." in response.content
    stock.refresh_from_db()
    assert stock.total_quantity == 10


def test_admin_records_reporter_restores_stock_and_retains_record(stock_admin, stock, tech):
    response = stock_admin.post(
        "/admin/equipment/equipmentunavailability/add/",
        {
            "equipment_type": stock.pk,
            "quantity": "2",
            "cause": "DAMAGED",
            "reason": "Lens damaged",
            "expected_return_at_0": "",
            "expected_return_at_1": "",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    record = EquipmentUnavailability.objects.get()
    assert record.reported_by == tech
    assert stock.unavailable_quantity == 2
    for _ in range(2):
        response = stock_admin.post(
            "/admin/equipment/equipmentunavailability/",
            {
                "action": "restore_stock",
                "_selected_action": [record.pk],
                "index": "0",
                "select_across": "0",
            },
        )
        assert response.status_code == 302
    record.refresh_from_db()
    assert record.restored_by == tech and record.restored_at is not None
    assert record.reason == "Lens damaged" and stock.unavailable_quantity == 0
    model_admin = EquipmentUnavailabilityAdmin(EquipmentUnavailability, admin.site)
    request = type("Request", (), {"user": tech})()
    assert not model_admin.has_change_permission(request, record)
    assert not model_admin.has_delete_permission(request, record)
    assert "equipment_type" in model_admin.get_readonly_fields(request, record)
    assert "equipment_type" not in model_admin.get_readonly_fields(request)


def test_admin_can_edit_active_unavailability_without_forging_reporter(stock_admin, stock, tech):
    record = EquipmentUnavailability.objects.create(
        equipment_type=stock, quantity=1, cause="DAMAGED", reason="Original", reported_by=tech
    )
    response = stock_admin.post(
        f"/admin/equipment/equipmentunavailability/{record.pk}/change/",
        {
            "quantity": "2",
            "cause": "MAINTENANCE",
            "reason": "Updated cause",
            "expected_return_at_0": "",
            "expected_return_at_1": "",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    record.refresh_from_db()
    assert record.quantity == 2 and record.reported_by == tech
    model_admin = EquipmentTypeAdmin(EquipmentType, admin.site)
    assert model_admin.get_readonly_fields(None) == []
    assert model_admin.get_readonly_fields(None, stock) == ["code"]


def test_non_staff_cannot_write_catalogue_and_workflow_admin_is_read_only(
    client, coordinator, stock
):
    client.force_login(coordinator)
    response = client.post(
        f"/admin/equipment/equipmenttype/{stock.pk}/change/", {"total_quantity": 0}
    )
    assert response.status_code == 302 and "/admin/login/" in response.url
    stock.refresh_from_db()
    assert stock.total_quantity == 10
    for model in [
        EquipmentPlan,
        EquipmentRequest,
        EquipmentReservation,
        TechnicalApproval,
        EquipmentHistory,
    ]:
        model_admin = admin.site._registry[model]
        assert isinstance(model_admin, ReadOnlyEquipmentAdmin)
        assert not model_admin.has_add_permission(None)
        assert not model_admin.has_change_permission(None)
        assert not model_admin.has_delete_permission(None)


def test_seed_requires_real_technical_staff():
    with pytest.raises(CommandError, match="Technical Support"):
        call_command("seed_equipment_catalogue")
    assert not EquipmentType.objects.exists()


def test_seed_repeatability_preserves_staff_edits_and_creates_no_fake_workflows(tech):
    call_command("seed_equipment_catalogue")
    projector = EquipmentType.objects.get(code="PROJECTOR")
    projector.total_quantity = 15
    projector.in_service = False
    projector.save()
    record = projector.unavailability_records.get()
    from apps.equipment.inventory import restore_unavailability

    restore_unavailability(record, tech)
    call_command("seed_equipment_catalogue")
    projector.refresh_from_db()
    assert EquipmentType.objects.count() == 3 and EquipmentUnavailability.objects.count() == 2
    assert projector.total_quantity == 15 and projector.in_service is False
    assert projector.unavailable_quantity == 0
    assert not EquipmentPlan.objects.exists()
    assert not EquipmentRequest.objects.exists()
    assert not EquipmentReservation.objects.exists()
    assert not TechnicalApproval.objects.exists()
    assert not EquipmentHistory.objects.exists()


def test_demo_seed_includes_equipment_with_exact_usable_and_unavailable_examples():
    call_command("seed_demo_data")
    call_command("seed_demo_data")
    projector = EquipmentType.objects.get(code="PROJECTOR")
    microphone = EquipmentType.objects.get(code="MICROPHONE")
    assert (projector.total_quantity, projector.unavailable_quantity) == (10, 2)
    assert (microphone.total_quantity, microphone.unavailable_quantity) == (12, 1)
    assert EquipmentType.objects.get(code="SPEAKER").unavailable_quantity == 0
