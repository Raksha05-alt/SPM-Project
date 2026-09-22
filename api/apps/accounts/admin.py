from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import ClientOrganisation, User


@admin.register(ClientOrganisation)
class ClientOrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email")
    search_fields = ("name",)


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("email", "first_name", "last_name", "role", "organisation")
    list_filter = ("role", "is_staff")
    ordering = ("email",)
    search_fields = ("email", "first_name", "last_name")
    fieldsets = UserAdmin.fieldsets + (("ConnectSphere", {"fields": ("role", "organisation")}),)
