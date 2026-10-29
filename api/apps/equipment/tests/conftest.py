import pytest

from apps.accounts.models import Role, User
from apps.equipment.models import EquipmentPlan, EquipmentRequest, EquipmentType


@pytest.fixture
def tech(db):
    return User.objects.create_user(
        username="equipment-tech", email="equipment-tech@example.com", role=Role.TECHNICAL_SUPPORT
    )


@pytest.fixture
def stock(db):
    return EquipmentType.objects.create(code="PROJECTOR", name="Projector", total_quantity=10)


@pytest.fixture
def plan(submitted_event):
    return EquipmentPlan.objects.create(event=submitted_event)


@pytest.fixture
def equipment_request(plan, stock, coordinator):
    return EquipmentRequest.objects.create(
        plan=plan,
        equipment_type=stock,
        quantity=8,
        technical_requirements="HDMI input; quiet fan",
        requested_by=coordinator,
    )
