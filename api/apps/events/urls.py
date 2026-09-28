from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.views import EventRequestViewSet, event_statuses

router = DefaultRouter()
router.register("events", EventRequestViewSet, basename="eventrequest")

urlpatterns = [
    path("event-statuses/", event_statuses, name="event-statuses"),
    path("", include(router.urls)),
]
