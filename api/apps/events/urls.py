from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.cancellation_views import CancelEventView, CancellationPreviewView
from apps.events.views import EventRequestViewSet, event_statuses

router = DefaultRouter()
router.register("events", EventRequestViewSet, basename="eventrequest")

urlpatterns = [
    path(
        "events/<int:event_id>/cancellation-preview/",
        CancellationPreviewView.as_view(),
        name="cancellation-preview",
    ),
    path("events/<int:event_id>/cancel/", CancelEventView.as_view(), name="cancel-event"),
    path("event-statuses/", event_statuses, name="event-statuses"),
    path("", include(router.urls)),
]
