from django.contrib import admin
from django.urls import include, path

from apps.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.events.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.venues.urls")),
    path("api/", include("apps.equipment.urls")),
]
