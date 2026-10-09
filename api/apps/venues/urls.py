from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.views import ShortlistEntryView, ShortlistView, VenueBlockViewSet, VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")
router.register("venue-blocks", VenueBlockViewSet, basename="venue-block")

urlpatterns = [
    path("events/<int:event_id>/shortlist/", ShortlistView.as_view(), name="venue-shortlist"),
    path(
        "events/<int:event_id>/shortlist/<int:venue_id>/",
        ShortlistEntryView.as_view(),
        name="venue-shortlist-entry",
    ),
    path("", include(router.urls)),
]
