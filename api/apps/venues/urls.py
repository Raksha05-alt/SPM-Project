from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.views import VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")

urlpatterns = [
    path("", include(router.urls)),
]
