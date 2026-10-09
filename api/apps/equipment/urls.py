from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.equipment.views import (
    EquipmentRequestViewSet,
    EquipmentReservationViewSet,
    EquipmentTypeViewSet,
)

router = SimpleRouter()
router.register("equipment", EquipmentTypeViewSet, basename="equipment")
router.register("equipment-requests", EquipmentRequestViewSet, basename="equipment-request")
router.register(
    "equipment-reservations", EquipmentReservationViewSet, basename="equipment-reservation"
)

urlpatterns = [path("", include(router.urls))]
