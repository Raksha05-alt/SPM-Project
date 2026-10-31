from django.contrib import admin

from apps.safety.models import SafetyCheck


@admin.register(SafetyCheck)
class SafetyCheckAdmin(admin.ModelAdmin):
    """Read-only: checks are evidence and change only through the services."""

    list_display = ("event", "status", "requested_by", "requested_at", "decided_by", "decided_at")
    list_filter = ("status",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
