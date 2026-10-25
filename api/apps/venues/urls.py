from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.availability_views import (
    AvailableVenuesView,
    BlockDetailView,
    BlockHistoryView,
    BlockView,
    CalendarView,
)
from apps.venues.views import VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")

urlpatterns = [
    path("venues/available/", AvailableVenuesView.as_view()),
    path("venues/<int:pk>/availability/", CalendarView.as_view()),
    path("venues/<int:pk>/blocks/", BlockView.as_view()),
    path("venues/<int:pk>/blocks/history/", BlockHistoryView.as_view()),
    path("venues/<int:pk>/blocks/<int:block_pk>/", BlockDetailView.as_view()),
    path("", include(router.urls)),
]
