from django.urls import path

from apps.equipment.action_views import (
    AmendEquipmentRequestView,
    ApproveRevisedEquipmentView,
    EquipmentPlanView,
    NoEquipmentApprovalView,
    ReleaseEquipmentView,
    ReserveEquipmentView,
    TechnicalPlanListView,
    WithdrawEquipmentRequestView,
)
from apps.equipment.views import (
    EquipmentHoldersView,
    EquipmentTypeListView,
    EventEquipmentAvailabilityView,
    EventEquipmentRequestsView,
    TechnicalEquipmentInboxView,
)

urlpatterns = [
    path("events/<int:event_id>/approve-revised-equipment/", ApproveRevisedEquipmentView.as_view()),
    path("equipment/requests/<int:request_id>/amend/", AmendEquipmentRequestView.as_view()),
    path("equipment/requests/<int:request_id>/withdraw/", WithdrawEquipmentRequestView.as_view()),
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
        "events/<int:event_id>/equipment-availability/<int:equipment_type_id>/",
        EquipmentHoldersView.as_view(),
        name="event-equipment-holders",
    ),
    path(
        "equipment/requests/",
        TechnicalEquipmentInboxView.as_view(),
        name="equipment-request-inbox",
    ),
]
