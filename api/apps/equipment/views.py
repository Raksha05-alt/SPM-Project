from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.mixins import CreateModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequest, EquipmentReservation, EquipmentType
from apps.equipment.serializers import (
    EquipmentRequestSerializer,
    EquipmentReviewInputSerializer,
    EquipmentTypeSerializer,
)
from apps.equipment.services import (
    EquipmentRefused,
    NotAllowed,
    amend_request,
    availability_row,
    create_request,
    holders,
    mark_unavailable,
    release,
    reserve,
    review_request,
    withdraw_request,
)
from apps.events.models import EventRequest
from apps.venues.availability import InvalidPeriod, parse_period

EQUIPMENT_ROLES = frozenset({Role.EVENT_COORDINATOR, Role.TECHNICAL_SUPPORT})
NOT_ASSIGNED = "Only the coordinator assigned to this event can do this."


def require_technical_staff(request, action_name, obj=None):
    if request.user.role != Role.TECHNICAL_SUPPORT:
        record_denied(request.user, action=action_name, obj=obj, detail="technical staff only")
        raise PermissionDenied("Only Technical Support Staff can do this.")


def period_and_event(request, action_name):
    """SCRUM-12 AC1 / AC6 - an event's period, or a chosen one (technical staff only)."""
    event_id = request.query_params.get("event")
    event = None
    if event_id:
        if not event_id.isdigit():
            raise ValidationError({"event": ["Must be an id."]})
        event = get_object_or_404(
            EventRequest.objects.exclude(status=EventStatus.DRAFT), pk=event_id
        )
    if request.user.role != Role.TECHNICAL_SUPPORT and (
        event is None or event.coordinator_id != request.user.pk
    ):
        record_denied(request.user, action=action_name, obj=event, detail="not permitted")
        raise PermissionDenied(
            "Only Technical Support Staff or the event's assigned coordinator can check this."
        )
    if request.query_params.get("start") or event is None:
        try:
            start, end = parse_period(
                request.query_params.get("start"), request.query_params.get("end")
            )
        except InvalidPeriod as exc:
            raise ValidationError({"detail": str(exc)}) from None
    else:
        if not (event.preferred_start and event.preferred_end):
            raise ValidationError({"detail": "The event has no date and time yet."})
        start, end = event.preferred_start, event.preferred_end
    return start, end, event


def refused(exc: EquipmentRefused) -> Response:
    return Response({"detail": exc.detail, **exc.extra}, status=exc.status)


class EquipmentTypeViewSet(ReadOnlyModelViewSet):
    """The equipment ConnectSphere owns; SCRUM-12 availability and SCRUM-76 holders."""

    queryset = EquipmentType.objects.all()
    serializer_class = EquipmentTypeSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = EQUIPMENT_ROLES

    @action(detail=False, methods=["get"])
    def availability(self, request):
        start, end, event = period_and_event(request, "GET /api/equipment/availability/")
        return Response(
            {
                "event": event.pk if event else None,
                "start": start,
                "end": end,
                "results": [
                    availability_row(item, start, end, event=event)
                    for item in EquipmentType.objects.all()
                ],
            }
        )

    @action(detail=True, methods=["get"])
    def holders(self, request, pk=None):
        item = self.get_object()
        start, end, _ = period_and_event(request, f"GET /api/equipment/{item.pk}/holders/")
        return Response(
            {
                "equipment": item.pk,
                "name": item.name,
                "out_of_service_quantity": item.out_of_service_quantity,
                "out_of_service_reason": item.out_of_service_reason,
                "expected_return": item.expected_return,
                "holding_events": holders(item, start, end),
            }
        )


class EquipmentRequestViewSet(CreateModelMixin, UpdateModelMixin, ReadOnlyModelViewSet):
    """SCRUM-74 record, SCRUM-75 amend/withdraw and SCRUM-16 reserve equipment."""

    serializer_class = EquipmentRequestSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = EQUIPMENT_ROLES
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        requests = (
            EquipmentRequest.objects.exclude(event__status=EventStatus.DRAFT)
            .select_related(
                "event", "equipment_type", "requested_by", "withdrawn_by", "reviewed_by"
            )
            .prefetch_related("reservations__reserved_by", "reservations__released_by", "changes")
        )
        event_id = self.request.query_params.get("event")
        if event_id:
            if not event_id.isdigit():
                raise ValidationError({"event": ["Must be an id."]})
            requests = requests.filter(event_id=int(event_id))
        return requests

    def _run(self, action_name, obj, work, success=http.HTTP_200_OK):
        try:
            result = work()
        except NotAllowed:
            record_denied(self.request.user, action=action_name, obj=obj, detail="not assigned")
            raise PermissionDenied(NOT_ASSIGNED) from None
        except EquipmentRefused as exc:
            return refused(exc)
        record(self.request.user, action_name, allowed=True, obj=result)
        request = self.get_queryset().get(pk=getattr(result, "request_id", result.pk))
        return Response(self.get_serializer(request).data, status=success)

    def _require_coordinator(self, action_name, obj=None):
        if self.request.user.role != Role.EVENT_COORDINATOR:
            record_denied(
                self.request.user, action=action_name, obj=obj, detail="coordinators only"
            )
            raise PermissionDenied(NOT_ASSIGNED)

    def create(self, request, *args, **kwargs):
        action_name = "POST /api/equipment-requests/"
        self._require_coordinator(action_name)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        event = data.pop("event")
        if event.status == EventStatus.DRAFT:
            raise PermissionDenied("Drafts are not visible to ConnectSphere.")
        return self._run(
            action_name,
            event,
            lambda: create_request(event, request.user, data),
            success=http.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        item = self.get_object()
        action_name = f"PATCH /api/equipment-requests/{item.pk}/"
        self._require_coordinator(action_name, item)
        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return self._run(
            action_name, item, lambda: amend_request(item, request.user, serializer.validated_data)
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        item = self.get_object()
        action_name = f"POST /api/equipment-requests/{item.pk}/withdraw/"
        self._require_coordinator(action_name, item)
        return self._run(action_name, item, lambda: withdraw_request(item, request.user))

    @action(detail=True, methods=["post"], url_path="mark-unavailable")
    def mark_unavailable(self, request, pk=None):
        item = self.get_object()
        action_name = f"POST /api/equipment-requests/{item.pk}/mark-unavailable/"
        require_technical_staff(request, action_name, item)
        return self._run(
            action_name,
            item,
            lambda: mark_unavailable(item, request.user, request.data.get("reason", "")),
        )

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """SCRUM-80 AC2 / AC3 - record the outcome of reviewing flagged equipment."""
        item = self.get_object()
        action_name = f"POST /api/equipment-requests/{item.pk}/review/"
        require_technical_staff(request, action_name, item)
        data = EquipmentReviewInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._run(
            action_name, item, lambda: review_request(item, request.user, **data.validated_data)
        )

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        item = self.get_object()
        action_name = f"POST /api/equipment-requests/{item.pk}/reserve/"
        require_technical_staff(request, action_name, item)
        return self._run(
            action_name, item, lambda: reserve(item, request.user), success=http.HTTP_201_CREATED
        )


class EquipmentReservationViewSet(GenericViewSet):
    """SCRUM-77 AC2 - Technical Support Staff release a reservation."""

    queryset = EquipmentReservation.objects.select_related("request")
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT})

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        reservation = self.get_object()
        action_name = f"POST /api/equipment-reservations/{reservation.pk}/release/"
        try:
            release(reservation, request.user, request.data.get("reason", ""))
        except EquipmentRefused as exc:
            return refused(exc)
        record(request.user, action_name, allowed=True, obj=reservation)
        item = EquipmentRequest.objects.get(pk=reservation.request_id)
        return Response(EquipmentRequestSerializer(item).data)
