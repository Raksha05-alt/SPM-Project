from django.contrib import admin

from apps.safety.models import SafetyCheck


@admin.register(SafetyCheck)
class SafetyCheckAdmin(admin.ModelAdmin):
    list_display = ("event", "status", "requested_at", "decided_by", "decided_at")
    list_filter = ("status",)
