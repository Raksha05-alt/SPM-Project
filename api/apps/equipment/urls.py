from django.urls import path

from apps.equipment.action_views import (
    EquipmentPlanView,
    NoEquipmentApprovalView,
    ReleaseEquipmentView,
    ReserveEquipmentView,
    TechnicalPlanListView,
)
from apps.equipment.views import (
    EquipmentTypeListView,
    EventEquipmentAvailabilityView,
    EventEquipmentRequestsView,
    TechnicalEquipmentInboxView,
)

urlpatterns = [
    path(
        "equipment/reservations/<int:reservation_id>/release/",
        ReleaseEquipmentView.as_view(),
        name="release-equipment",
    ),
    path("equipment/plans/", TechnicalPlanListView.as_view(), name="equipment-plans"),
    path(
        "events/<int:event_id>/equipment-plan/", EquipmentPlanView.as_view(), name="equipment-plan"
    ),
    path(
        "equipment/requests/<int:request_id>/reserve/",
        ReserveEquipmentView.as_view(),
        name="reserve-equipment",
    ),
    path(
        "events/<int:event_id>/approve-no-equipment/",
        NoEquipmentApprovalView.as_view(),
        name="approve-no-equipment",
    ),
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
