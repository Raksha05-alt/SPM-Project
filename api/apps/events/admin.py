from django.contrib import admin

from apps.events.models import EventRequest, EventStatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = EventStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at")
    can_delete = False


@admin.register(EventRequest)
class EventRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation", "status", "preferred_start", "submitted_at")
    list_filter = ("status", "organisation")
    search_fields = ("name", "purpose")
    inlines = [StatusHistoryInline]
