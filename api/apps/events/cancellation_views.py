"""Assigned-coordinator cancellation: preview, explicit confirmation and one transaction."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.equipment.reservations import EquipmentActionDenied, EquipmentActionError
from apps.events.cancellation import cancel_event, cancellation_preview
from apps.events.models import EventRequest


class CancellationView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def perform(self, request, event_id, callback):
        event = get_object_or_404(EventRequest, pk=event_id)
        try:
            return Response(callback(event))
        except EquipmentActionDenied as exc:
            record_denied(
                request.user, action=f"{request.method} {request.path}", obj=event, detail=str(exc)
            )
            raise PermissionDenied(str(exc)) from None
        except EquipmentActionError as exc:
            return Response({"detail": exc.detail, **exc.fields}, status=exc.status)


class CancellationPreviewView(CancellationView):
    def get(self, request, event_id):
        return self.perform(
            request, event_id, lambda event: cancellation_preview(event, request.user)
        )


class CancelEventView(CancellationView):
    def post(self, request, event_id):
        if not isinstance(request.data, dict):
            raise ValidationError("Supply a JSON object for cancellation.")
        return self.perform(
            request,
            event_id,
            lambda event: cancel_event(
                event=event,
                actor=request.user,
                expected_version=request.data.get("expected_version"),
                confirm_cancel=request.data.get("confirm_cancel", False),
                reason=request.data.get("reason", ""),
            ),
        )
