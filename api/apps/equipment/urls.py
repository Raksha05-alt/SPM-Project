from django.urls import path

from apps.equipment.views import (
    EquipmentTypeListView,
    EventEquipmentAvailabilityView,
    EventEquipmentRequestsView,
    TechnicalEquipmentInboxView,
)

urlpatterns = [
    path("equipment/types/", EquipmentTypeListView.as_view(), name="equipment-types"),
    path(
        "events/<int:event_id>/equipment-requests/",
        EventEquipmentRequestsView.as_view(),
        name="event-equipment-requests",
    ),
    path(
        "events/<int:event_id>/equipment-availability/",
        EventEquipmentAvailabilityView.as_view(),
        name="event-equipment-availability",
    ),
    path(
        "equipment/requests/",
        TechnicalEquipmentInboxView.as_view(),
        name="equipment-request-inbox",
    ),
]
