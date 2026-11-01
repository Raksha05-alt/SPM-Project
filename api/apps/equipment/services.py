"""SCRUM-74 - the assigned coordinator records the equipment an event requires.

Sprint 3 gate G14. Reservation (SCRUM-16), release (SCRUM-77) and amendment or
withdrawal (SCRUM-75) are separate actions owned by later gates; this module
only creates requests.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types, validate_quantity
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
)

# Equipment is planned once the event is approved, as venues are (SCRUM-11).
EVENT_STATUSES_OPEN_TO_REQUESTS = frozenset({EventStatus.APPROVED, EventStatus.PLANNING})


class NotAssignedToEvent(Exception):
    """AC5 - only the event's assigned coordinator may add an equipment request."""


class EquipmentRequestError(Exception):
    """AC2 and the guide's refusals - every problem by field; nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))


def _clean(equipment_type, quantity, technical_requirements) -> dict:
    errors = {}
    if equipment_type in (None, ""):
        errors["equipment_type"] = "Choose the equipment type."
    elif isinstance(equipment_type, bool) or not isinstance(equipment_type, int):
        errors["equipment_type"] = "Choose an equipment type from the catalogue."
    if quantity in (None, ""):
        errors["quantity"] = "Enter the quantity required."
    else:
        try:
            validate_quantity(quantity)
        except DjangoValidationError:
            # AC2 - zero, negative and non-whole quantities are refused.
            errors["quantity"] = "The quantity must be a whole number of 1 or more."
    if technical_requirements is None:
        technical_requirements = ""
    if not isinstance(technical_requirements, str):
        errors["technical_requirements"] = "Technical requirements must be text."
    if errors:
        raise EquipmentRequestError(errors)
    return {
        "equipment_type": equipment_type,
        "quantity": quantity,
        "technical_requirements": technical_requirements.strip(),
    }


def _snapshot(request: EquipmentRequest) -> dict:
    return {
        "equipment_type": request.equipment_type_id,
        "quantity": request.quantity,
        "technical_requirements": request.technical_requirements,
        "status": request.status,
    }


@transaction.atomic
def create_request(
    *, event, requested_by, equipment_type=None, quantity=None, technical_requirements=""
) -> EquipmentRequest:
    """SCRUM-74 - save one equipment request for ``event``.

    Locks the event, then the equipment type (the shared lock order). Refuses,
    with nothing saved, when the user is not the assigned coordinator (AC5), the
    event is not Approved or Planning, the type is unknown, retired or already
    requested, or the quantity is not a positive whole number (AC2). On success
    it saves the request with who and when (AC4) and a history row, moves an
    Approved event to Planning, marks the equipment plan as changed so an
    earlier technical approval or Safety check no longer covers it, and
    notifies Technical Support (AC4).
    """
    from apps.accounts.models import Role, User
    from apps.events.models import EventRequest
    from apps.events.services import transition_event
    from apps.notifications.models import Notification, NotificationKind
    from apps.safety.services import arrangements_changed

    locked_event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked_event.coordinator_id is None or locked_event.coordinator_id != requested_by.pk:
        raise NotAssignedToEvent
    if locked_event.status not in EVENT_STATUSES_OPEN_TO_REQUESTS:
        raise EquipmentRequestError(
            {
                "event": (
                    "Equipment can be requested once the event is approved; "
                    f"this event is {locked_event.get_status_display()}."
                )
            }
        )
    cleaned = _clean(equipment_type, quantity, technical_requirements)
    try:
        [item] = lock_equipment_types([cleaned["equipment_type"]])
    except DjangoValidationError:
        raise EquipmentRequestError(
            {"equipment_type": "That equipment type is not in the catalogue."}
        ) from None
    if not item.in_service:
        raise EquipmentRequestError(
            {"equipment_type": f"{item.name} is no longer offered for events."}
        )

    plan, _ = EquipmentPlan.objects.select_for_update().get_or_create(event=locked_event)
    if (
        plan.requests.filter(equipment_type=item)
        .exclude(status=EquipmentRequestStatus.WITHDRAWN)
        .exists()
    ):
        raise EquipmentRequestError(
            {
                "equipment_type": (
                    f"{item.name} is already requested for this event. Change that request instead."
                )
            }
        )

    if locked_event.status == EventStatus.APPROVED:
        transition_event(locked_event, EventStatus.PLANNING, requested_by)

    # A new line changes the equipment plan: an approval of the old revision
    # no longer covers it (apps.safety.services._current_technical_approval).
    plan.revision += 1
    plan.save(update_fields=["revision", "updated_at"])
    request = EquipmentRequest.objects.create(
        plan=plan,
        equipment_type=item,
        quantity=cleaned["quantity"],
        technical_requirements=cleaned["technical_requirements"],
        requested_by=requested_by,
    )
    EquipmentHistory.objects.create(
        plan=plan,
        request=request,
        action=EquipmentHistoryAction.REQUESTED,
        plan_revision=plan.revision,
        after=_snapshot(request),
        actor=requested_by,
    )
    # INT-04 - the arrangement version includes open equipment requests.
    arrangements_changed(
        locked_event,
        f"{request.quantity} x {item.name} was requested.",
        requested_by,
    )

    staff = User.objects.filter(role=Role.TECHNICAL_SUPPORT, is_active=True)
    name = requested_by.get_full_name() or requested_by.email
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=member,
                event=locked_event,
                kind=NotificationKind.EQUIPMENT_REQUESTED,
                message=(
                    f'{name} requested {request.quantity} x {item.name} for "{locked_event.name}". '
                    "Review it in Equipment."
                ),
            )
            for member in staff
        ]
    )
    return request
