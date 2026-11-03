"""SCRUM-58 - Confirm an event after its essential arrangements are complete.

GET  /api/events/<id>/readiness/                 coordinator's Readiness panel (AC1/AC2)
POST /api/events/<id>/confirm/                   the assigned coordinator confirms (AC1/AC4/AC5)
GET  /api/events/<id>/confirmed-arrangements/    the confirmed plan, for the organiser (AC5)
POST /api/equipment/requests/<id>/unavailable/   Technical Support record unavailability (AC3)

Every refusal is audited.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequest
from apps.equipment.reservations import EquipmentActionDenied, EquipmentActionError
from apps.events.confirmation import (
    ConfirmationBlocked,
    ConfirmationRefused,
    confirm_event,
    confirmed_arrangements,
    readiness,
    record_equipment_unavailable,
)
from apps.events.models import EventRequest
from apps.events.serializers import EventRequestSerializer
from apps.events.services import NotAssignedCoordinator

ASSIGNED_ONLY = "Only the coordinator assigned to this event can do this."


def _event(pk):
    return get_object_or_404(
        EventRequest.objects.select_related("organisation", "coordinator", "confirmed_by"), pk=pk
    )


def _refuse(request, event, detail, message):
    record_denied(request.user, action=f"{request.method} {request.path}", obj=event, detail=detail)
    raise PermissionDenied(message)


class EventReadinessView(APIView):
    """AC1/AC2 - what stands between the event and confirmation."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD})

    def get(self, request, event_id):
        event = _event(event_id)
        if event.status == EventStatus.DRAFT:
            _refuse(request, event, "drafts are not visible", "This event is not available.")
        if request.user.is_coordinator and event.coordinator_id != request.user.pk:
            _refuse(request, event, "event is not assigned to this coordinator", ASSIGNED_ONLY)
        return Response(readiness(event))


class ConfirmEventView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def post(self, request, event_id):
        event = _event(event_id)
        try:
            confirmed = confirm_event(event, request.user)
        except NotAssignedCoordinator:
            _refuse(request, event, "only the assigned coordinator may confirm", ASSIGNED_ONLY)
        except ConfirmationRefused as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_409_CONFLICT)
        except ConfirmationBlocked as exc:
            # AC2 - confirmation is blocked and each missing item is listed.
            return Response(
                {
                    "detail": "This event cannot be confirmed yet.",
                    "missing": exc.missing,
                    "readiness": readiness(event),
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "detail": f'"{confirmed.name}" is confirmed. The Event Organiser has been notified.',
                "event": EventRequestSerializer(
                    _event(confirmed.pk), context={"request": request}
                ).data,
            }
        )


class ConfirmedArrangementsView(APIView):
    """AC5 - the organiser sees the confirmed arrangements of their own event."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset(
        {Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD}
    )

    def get(self, request, event_id):
        event = _event(event_id)
        user = request.user
        if user.role == Role.EVENT_ORGANISER and event.organisation_id != user.organisation_id:
            _refuse(
                request,
                event,
                "event belongs to another client organisation",
                "You do not have access to this event.",
            )
        if user.is_coordinator and event.coordinator_id != user.pk:
            _refuse(request, event, "event is not assigned to this coordinator", ASSIGNED_ONLY)
        if event.status not in (EventStatus.CONFIRMED, EventStatus.COMPLETED):
            return Response(
                {"detail": "This event has not been confirmed yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(confirmed_arrangements(event))


class EquipmentUnavailableView(APIView):
    """AC3 - Technical Support record that a requested item cannot be provided."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT})

    def post(self, request, request_id):
        item = get_object_or_404(
            EquipmentRequest.objects.select_related("plan__event", "equipment_type"), pk=request_id
        )
        reason = request.data.get("reason", "") if isinstance(request.data, dict) else ""
        try:
            record_equipment_unavailable(equipment_request=item, actor=request.user, reason=reason)
        except EquipmentActionDenied as exc:
            _refuse(request, item.plan.event, str(exc), str(exc))
        except EquipmentActionError as exc:
            return Response({"detail": exc.detail, **exc.fields}, status=exc.status)
        return Response(
            {
                "detail": (
                    f"Recorded {item.quantity} x {item.equipment_type.name} as unavailable. "
                    "The coordinator and the Event Organiser have been told why."
                )
            }
        )
