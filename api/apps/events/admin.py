from django.contrib import admin

from apps.events.models import CoordinatorAssignment, EventRequest, EventStatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = EventStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at")
    can_delete = False


class AssignmentHistoryInline(admin.TabularInline):
    model = CoordinatorAssignment
    extra = 0
    readonly_fields = (
        "previous_coordinator",
        "coordinator",
        "assigned_by",
        "previous_supervising_lead",
        "revision",
        "assigned_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(EventRequest)
class EventRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation", "status", "preferred_start", "submitted_at")
    list_filter = ("status", "organisation")
    search_fields = ("name", "purpose")
    inlines = [StatusHistoryInline, AssignmentHistoryInline]
    readonly_fields = (
        "coordinator",
        "supervising_lead",
        "assignment_revision",
        "assignment_requires_attention",
    )
