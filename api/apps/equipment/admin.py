from django.contrib import admin

from apps.equipment.models import EquipmentRequest, EquipmentReservation, EquipmentType


@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "total_quantity", "out_of_service_quantity"]
    search_fields = ["name", "category"]


@admin.register(EquipmentRequest)
class EquipmentRequestAdmin(admin.ModelAdmin):
    list_display = ["event", "equipment_type", "quantity", "status"]
    list_filter = ["status"]


@admin.register(EquipmentReservation)
class EquipmentReservationAdmin(admin.ModelAdmin):
    list_display = ["event", "equipment_type", "quantity", "start", "end", "released_at"]
