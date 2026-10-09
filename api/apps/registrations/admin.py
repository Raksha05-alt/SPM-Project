from django.contrib import admin

from apps.registrations.models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ["full_name", "event", "status", "registered_at"]
    list_filter = ["status"]
