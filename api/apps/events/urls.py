from rest_framework.routers import DefaultRouter

from apps.events.views import EventRequestViewSet

router = DefaultRouter()
router.register("events", EventRequestViewSet, basename="eventrequest")
urlpatterns = router.urls
