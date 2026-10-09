from django.contrib import admin

from apps.venues.models import Venue, VenueBlock, VenueBooking


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "capacity", "is_active")
    search_fields = ("name", "location")


@admin.register(VenueBlock)
class VenueBlockAdmin(admin.ModelAdmin):
    list_display = ("venue", "start", "end", "reason", "removed_at")


@admin.register(VenueBooking)
class VenueBookingAdmin(admin.ModelAdmin):
    list_display = ("venue", "event", "start", "end", "status", "review_required")
    list_filter = ("status", "review_required")
