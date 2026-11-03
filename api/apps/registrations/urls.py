from django.urls import path

from apps.registrations.views import (
    EventRegistrationsView,
    MyRegistrationsView,
    RegisterView,
    RegistrationPolicyView,
)

urlpatterns = [
    # SCRUM-21/81 - attendee registration and the organiser's registration policy.
    path("events/<int:event_id>/registration/", RegisterView.as_view(), name="event-register"),
    path("registrations/mine/", MyRegistrationsView.as_view(), name="my-registrations"),
    path(
        "events/<int:event_id>/registration-policy/",
        RegistrationPolicyView.as_view(),
        name="registration-policy",
    ),
    path(
        "events/<int:event_id>/registrations/",
        EventRegistrationsView.as_view(),
        name="event-registrations",
    ),
]
