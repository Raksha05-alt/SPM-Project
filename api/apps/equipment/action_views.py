"""SCRUM-16/77: scoped equipment plan reads and authorised resource actions."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequest,
    EquipmentReservation,
    TechnicalApprovalStatus,
)
from apps.equipment.reservations import (
    OPEN_STATUSES,
    EquipmentActionDenied,
    EquipmentActionError,
    approve_no_equipment,
    reserve,
)
from apps.equipment.views import EquipmentRequestSerializer, _requests
from apps.events.models import EventRequest


def reservation_data(reservation):
    return {
        "id": reservation.pk,
        "request": reservation.request_id,
        "quantity": reservation.quantity,
        "starts_at": reservation.starts_at,
        "ends_at": reservation.ends_at,
        "status": reservation.status,
        "reserved_by_name": reservation.reserved_by.get_full_name()
        or reservation.reserved_by.email,
        "reserved_at": reservation.reserved_at,
        "released_by_name": (
            reservation.released_by.get_full_name() or reservation.released_by.email
            if reservation.released_by_id
            else None
        ),
        "released_at": reservation.released_at,
        "release_reason": reservation.release_reason,
    }


def plan_data(event):
    plan = EquipmentPlan.objects.filter(event=event).first()
    approval = (
        plan.technical_approvals.filter(status=TechnicalApprovalStatus.APPROVED).first()
        if plan
        else None
    )
    return {
        "event": {
            "id": event.pk,
            "name": event.name,
            "status": event.status,
            "starts_at": event.preferred_start,
            "ends_at": event.preferred_end,
        },
        "revision": plan.revision if plan else 0,
        "requests": EquipmentRequestSerializer(
            _requests().filter(plan__event=event), many=True
        ).data,
        "reservations": [
            reservation_data(r)
            for r in (
                EquipmentReservation.objects.filter(request__plan=plan)
                .select_related("reserved_by", "released_by")
                .order_by("pk")
            )
        ]
        if plan
        else [],
        "technical_approval": (
            {
                "id": approval.pk,
                "revision": approval.plan_revision,
                "no_equipment_required": approval.no_equipment_required,
                "notes": approval.notes,
                "approved_by_name": approval.approved_by.get_full_name()
                or approval.approved_by.email,
                "approved_at": approval.approved_at,
            }
            if approval and approval.plan_revision == plan.revision
            else None
        ),
    }


class EquipmentPlanView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT, Role.EVENT_COORDINATOR})

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        if event.status == EventStatus.DRAFT or (
            request.user.role == Role.EVENT_COORDINATOR and event.coordinator_id != request.user.pk
        ):
            record_denied(
                request.user,
                action=f"GET {request.path}",
                obj=event,
                detail="equipment plan access",
            )
            raise PermissionDenied("You do not have access to this event's equipment plan.")
        return Response(plan_data(event))


class TechnicalPlanListView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT})

    def get(self, request):
        return Response(
            list(
                EventRequest.objects.filter(status__in=OPEN_STATUSES)
                .order_by("preferred_start", "pk")
                .values("id", "name")
            )
        )


class EquipmentActionView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT})

    def perform(self, request, event, callback):
        if not isinstance(request.data, dict):
            raise ValidationError("Supply a JSON object for the equipment action.")
        try:
            callback()
        except EquipmentActionDenied as exc:
            record_denied(request.user, action=f"POST {request.path}", obj=event, detail=str(exc))
            raise PermissionDenied(str(exc)) from None
        except EquipmentActionError as exc:
            return Response({"detail": exc.detail, **exc.fields}, status=exc.status)
        event.refresh_from_db()
        return Response(plan_data(event))


class ReserveEquipmentView(EquipmentActionView):
    def post(self, request, request_id):
        item = get_object_or_404(
            EquipmentRequest.objects.select_related("plan__event"), pk=request_id
        )
        return self.perform(
            request,
            item.plan.event,
            lambda: reserve(
                equipment_request=item,
                actor=request.user,
                expected_revision=request.data.get("expected_revision"),
            ),
        )


class NoEquipmentApprovalView(EquipmentActionView):
    def post(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        return self.perform(
            request,
            event,
            lambda: approve_no_equipment(
                event=event,
                actor=request.user,
                expected_revision=request.data.get("expected_revision"),
                acknowledged=request.data.get("acknowledged"),
                notes=request.data.get("notes", ""),
            ),
        )


class ReleaseEquipmentView(EquipmentActionView):
    def post(self, request, reservation_id):
        from apps.equipment.releases import release

        reservation = get_object_or_404(
            EquipmentReservation.objects.select_related("request__plan__event"),
            pk=reservation_id,
        )
        return self.perform(
            request,
            reservation.request.plan.event,
            lambda: release(
                reservation=reservation,
                actor=request.user,
                expected_revision=request.data.get("expected_revision"),
                reason=request.data.get("reason", ""),
            ),
        )
