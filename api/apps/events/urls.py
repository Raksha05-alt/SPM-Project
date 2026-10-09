from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.change_views import (
    ChangeDecisionView,
    ChangeRequestDetailView,
    EventChangeRequestsView,
)
from apps.events.views import EventRequestViewSet, coordinators, event_statuses

router = DefaultRouter()
router.register("events", EventRequestViewSet, basename="eventrequest")

urlpatterns = [
    path("event-statuses/", event_statuses, name="event-statuses"),
    path("coordinators/", coordinators, name="coordinators"),
    path(
        "events/<int:event_id>/change-requests/",
        EventChangeRequestsView.as_view(),
        name="event-change-requests",
    ),
    path("change-requests/<int:pk>/", ChangeRequestDetailView.as_view(), name="change-request"),
    path(
        "change-requests/<int:pk>/approve/",
        ChangeDecisionView.as_view(approve=True),
        name="change-request-approve",
    ),
    path(
        "change-requests/<int:pk>/reject/",
        ChangeDecisionView.as_view(approve=False),
        name="change-request-reject",
    ),
    path("", include(router.urls)),
]
