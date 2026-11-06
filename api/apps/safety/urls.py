from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.safety.views import EventSafetyChecksView, SafetyCheckViewSet

router = SimpleRouter()
router.register("safety-checks", SafetyCheckViewSet, basename="safety-check")

urlpatterns = [
    path(
        "events/<int:event_id>/safety-checks/",
        EventSafetyChecksView.as_view(),
        name="event-safety-checks",
    ),
    path("", include(router.urls)),
]
