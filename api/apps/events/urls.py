from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.cancellation_views import CancelEventView, CancellationPreviewView
from apps.events.confirmation_views import (
    ConfirmedArrangementsView,
    ConfirmEventView,
    EquipmentUnavailableView,
    EventReadinessView,
)
from apps.events.history_views import EventChangeHistoryView
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
    # SCRUM-58 - confirm an event once its essential arrangements are complete.
    path("events/<int:event_id>/readiness/", EventReadinessView.as_view(), name="event-readiness"),
    path("events/<int:event_id>/confirm/", ConfirmEventView.as_view(), name="confirm-event"),
    path(
        "events/<int:event_id>/confirmed-arrangements/",
        ConfirmedArrangementsView.as_view(),
        name="confirmed-arrangements",
    ),
    path(
        "equipment/requests/<int:request_id>/unavailable/",
        EquipmentUnavailableView.as_view(),
        name="equipment-unavailable",
    ),
    # SCRUM-60 - internal before/after history; reads only.
    path(
        "events/<int:event_id>/change-history/",
        EventChangeHistoryView.as_view(),
        name="event-change-history",
    ),
    path("event-statuses/", event_statuses, name="event-statuses"),
    path("", include(router.urls)),
]
