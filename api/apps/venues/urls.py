from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.suitability_views import EventVenueSuitabilityView
from apps.venues.views import VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")

urlpatterns = [
    path("", include(router.urls)),
    # SCRUM-71 - venue suitability for an event.
    path(
        "events/<int:event_id>/venue-suitability/",
        EventVenueSuitabilityView.as_view(),
        name="event-venue-suitability",
    ),
    path(
        "events/<int:event_id>/venue-suitability/<int:venue_id>/",
        EventVenueSuitabilityView.as_view(),
        name="event-venue-suitability-detail",
    ),
]
