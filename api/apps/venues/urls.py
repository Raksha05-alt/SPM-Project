from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.availability_views import (
    AvailableVenuesView,
    BlockDetailView,
    BlockHistoryView,
    BlockView,
    CalendarView,
)
from apps.venues.discovery_views import (
    EventVenueShortlistItemView,
    EventVenueShortlistView,
    VenueSearchView,
)
from apps.venues.layout_views import LayoutTypeViewSet
from apps.venues.views import VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")
router.register("layouts", LayoutTypeViewSet, basename="layout-type")

urlpatterns = [
    path("venues/available/", AvailableVenuesView.as_view()),
    path("venues/<int:pk>/availability/", CalendarView.as_view()),
    path("venues/<int:pk>/blocks/", BlockView.as_view()),
    path("venues/<int:pk>/blocks/history/", BlockHistoryView.as_view()),
    path("venues/<int:pk>/blocks/<int:block_pk>/", BlockDetailView.as_view()),
    path("venues/search/", VenueSearchView.as_view(), name="venue-search"),
    path(
        "events/<int:event_id>/venue-shortlist/",
        EventVenueShortlistView.as_view(),
        name="venue-shortlist",
    ),
    path(
        "events/<int:event_id>/venue-shortlist/<int:venue_id>/",
        EventVenueShortlistItemView.as_view(),
        name="venue-shortlist-item",
    ),
    path("", include(router.urls)),
]
