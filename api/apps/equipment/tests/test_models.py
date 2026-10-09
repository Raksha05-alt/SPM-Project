import pytest

from apps.equipment.models import EquipmentRequestChange
from apps.equipment.tests.conftest import hold


@pytest.mark.django_db
def test_equipment_records_describe_themselves(event, projector):
    reservation = hold(event, projector, 2)
    change = EquipmentRequestChange.objects.create(
        request=reservation.request, description="Quantity changed from 1 to 2."
    )
    projector.out_of_service_quantity = 12

    assert str(projector) == "Projector"
    assert projector.in_service_quantity == 0
    assert str(reservation.request) == f"2 x Projector for event {event.pk}"
    assert str(reservation) == f"2 x Projector for event {event.pk}"
    assert str(change) == "Quantity changed from 1 to 2."
