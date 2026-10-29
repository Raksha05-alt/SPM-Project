from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from apps.equipment.inventory import (
    restore_unavailability,
    save_equipment_type,
    save_unavailability,
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


class CatalogueAdmin(admin.ModelAdmin):
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as exc:
            # A concurrent stock change may invalidate an already-valid form.
            self.message_user(request, " ".join(exc.messages), level=messages.ERROR)
            return redirect(request.path)


@admin.register(EquipmentType)
class EquipmentTypeAdmin(CatalogueAdmin):
    list_display = ["code", "name", "total_quantity", "unavailable_quantity", "in_service"]
    search_fields = ["code", "name"]
    list_filter = ["in_service"]

    def get_readonly_fields(self, request, obj=None):
        return ["code"] if obj else []

    def save_model(self, request, obj, form, change):
        save_equipment_type(obj)


@admin.register(EquipmentUnavailability)
class EquipmentUnavailabilityAdmin(CatalogueAdmin):
    list_display = ["equipment_type", "quantity", "cause", "expected_return_at", "restored_at"]
    list_filter = ["cause", "restored_at"]
    readonly_fields = ["reported_by", "restored_by", "restored_at", "created_at", "updated_at"]
    actions = ["restore_stock"]

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, *(["equipment_type"] if obj else [])]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.restored_at is None
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.reported_by = request.user
        save_unavailability(obj)

    @admin.action(description="Restore selected unavailable stock", permissions=["change"])
    def restore_stock(self, request, queryset):
        for record in queryset.order_by("equipment_type_id", "pk"):
            restore_unavailability(record, request.user)


class ReadOnlyEquipmentAdmin(admin.ModelAdmin):
    """Workflow data can only be written by the future authorised action services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    EquipmentPlan,
    EquipmentRequest,
    EquipmentReservation,
    TechnicalApproval,
    EquipmentHistory,
):
    admin.site.register(model, ReadOnlyEquipmentAdmin)
