from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.registrations.views import EventRegistrationsView, RegistrationViewSet, WaitlistView

router = SimpleRouter()
router.register("registrations", RegistrationViewSet, basename="registration")

urlpatterns = [
    path(
        "events/<int:event_id>/registrations/",
        EventRegistrationsView.as_view(),
        name="event-registrations",
    ),
    path("events/<int:event_id>/waitlist/", WaitlistView.as_view(), name="event-waitlist"),
    path("", include(router.urls)),
]
