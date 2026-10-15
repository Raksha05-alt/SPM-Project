from django.contrib import admin

from apps.venues.models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "capacity", "in_service", "updated_at")
    list_filter = ("in_service",)
    search_fields = ("name", "location")
