"""SCRUM-74 - Record equipment required for an event (Sprint 3 gate G14).

GET  /api/equipment/types/                     the in-service catalogue to choose from
GET  /api/events/<event_id>/equipment-requests/ the event's equipment requests (AC3)
POST /api/events/<event_id>/equipment-requests/ the assigned coordinator adds one (AC1)
GET  /api/equipment/requests/                  Technical Support: events with requests (AC3)

SCRUM-12 (G15):
GET  /api/events/<event_id>/equipment-availability/  availability for the event period

Technical Support get a scoped, read-only view: only events that have equipment
requested, with only the event fields they need to fulfil them. Clients and
Attendees never reach equipment requests. Every refusal is audited.
"""

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentRequest, EquipmentRequestStatus, EquipmentType
from apps.equipment.services import EquipmentRequestError, NotAssignedToEvent, create_request
from apps.events.models import EventRequest


def _name(user):
    return None if user is None else (user.get_full_name() or user.email)


class EquipmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentType
        fields = ["id", "code", "name", "description"]


class EquipmentRequestSerializer(serializers.ModelSerializer):
    event = serializers.IntegerField(source="plan.event_id", read_only=True)
    equipment_type_name = serializers.CharField(source="equipment_type.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentRequest
        fields = [
            "id",
            "event",
            "equipment_type",
            "equipment_type_name",
            "quantity",
            "technical_requirements",
            "status",
            "status_label",
            "requested_by_name",
            "requested_at",
        ]

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)


class EquipmentRequestInputSerializer(serializers.Serializer):
    """Parses the request without coercion; the service names every problem (AC2)."""

    equipment_type = serializers.JSONField(required=False, allow_null=True)
    quantity = serializers.JSONField(required=False, allow_null=True)
    technical_requirements = serializers.JSONField(required=False, allow_null=True)


def _requests():
    return EquipmentRequest.objects.select_related("plan", "equipment_type", "requested_by")


def _has_open_requests():
    return Exists(
        EquipmentRequest.objects.filter(plan__event=OuterRef("pk")).exclude(
            status=EquipmentRequestStatus.WITHDRAWN
        )
    )


class CanSeeEventEquipment(BasePermission):
    """Assigned coordinator, any Lead, or Technical Support for an event with requests."""

    message = "You do not have access to this event's equipment requests."

    def has_object_permission(self, request, view, event):
        user = request.user
        if event.status == EventStatus.DRAFT:
            allowed, reason = False, "drafts are not visible to ConnectSphere"
        elif user.role == Role.EVENT_COORDINATOR:
            allowed = event.coordinator_id == user.pk
            reason = "coordinator is not assigned to this event"
        elif user.role == Role.TECHNICAL_SUPPORT:
            allowed = EventRequest.objects.filter(pk=event.pk).filter(_has_open_requests()).exists()
            reason = "no equipment has been requested for this event"
        else:
            allowed, reason = True, ""
        if not allowed:
            record_denied(user, action=f"{request.method} {request.path}", obj=event, detail=reason)
        return allowed


class EquipmentTypeListView(APIView):
    """The catalogue a coordinator chooses from; retired types are not offered."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset(
        {Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD, Role.TECHNICAL_SUPPORT}
    )

    def get(self, request):
        types = EquipmentType.objects.filter(in_service=True).order_by("name", "pk")
        return Response(EquipmentTypeSerializer(types, many=True).data)


class EventEquipmentRequestsView(APIView):
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, CanSeeEventEquipment]

    @property
    def allowed_roles(self):
        if self.request.method == "POST":
            # AC5 - only coordinators add requests; the service checks assignment.
            return frozenset({Role.EVENT_COORDINATOR})
        return frozenset(
            {Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD, Role.TECHNICAL_SUPPORT}
        )

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        requests = _requests().filter(plan__event=event).order_by("requested_at", "pk")
        return Response(EquipmentRequestSerializer(requests, many=True).data)

    def post(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        action = f"POST /api/events/{event_id}/equipment-requests/"
        payload = EquipmentRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            created = create_request(
                event=event, requested_by=request.user, **payload.validated_data
            )
        except NotAssignedToEvent:
            record_denied(
                request.user,
                action=action,
                obj=event,
                detail="only the assigned coordinator may request equipment",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can request equipment."
            ) from None
        except EquipmentRequestError as exc:
            return Response(
                {
                    "detail": "The equipment request could not be saved.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                # AC4 - confirmation that the request reached Technical Support.
                "detail": (
                    f"Your request for {created.quantity} x {created.equipment_type.name} "
                    "has been sent to Technical Support."
                ),
                "request": EquipmentRequestSerializer(_requests().get(pk=created.pk)).data,
            },
            status=status.HTTP_201_CREATED,
        )


class TechnicalEventSerializer(serializers.ModelSerializer):
    """Only what Technical Support need to fulfil the equipment (guide: scoped read)."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    coordinator_name = serializers.SerializerMethodField()
    equipment_requests = EquipmentRequestSerializer(
        source="equipment_plan.requests", many=True, read_only=True
    )

    class Meta:
        model = EventRequest
        fields = [
            "id",
            "name",
            "status",
            "status_label",
            "preferred_start",
            "preferred_end",
            "expected_attendance",
            "coordinator_name",
            "equipment_requests",
        ]

    def get_coordinator_name(self, obj):
        return _name(obj.coordinator)


class TechnicalEquipmentInboxView(APIView):
    """AC3 - Technical Support see every event with requested equipment, soonest first."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT})

    def get(self, request):
        events = (
            EventRequest.objects.filter(_has_open_requests())
            .select_related("coordinator", "equipment_plan")
            .prefetch_related(
                Prefetch(
                    "equipment_plan__requests",
                    queryset=_requests().order_by("requested_at", "pk"),
                )
            )
            .order_by("preferred_start", "pk")
        )
        return Response(TechnicalEventSerializer(events, many=True).data)


# --------------------------------------------------------------------------
# SCRUM-12 - equipment availability for an event period (Sprint 3 gate G15)
# --------------------------------------------------------------------------


class CanCheckEventAvailability(BasePermission):
    """AC6 - Technical Support (for an event with equipment requested) or the
    event's assigned coordinator. Everyone else is refused and audited, and the
    refusal names no other event or reservation."""

    message = "Only Technical Support or the event's coordinator can check its equipment."

    def has_object_permission(self, request, view, event):
        user = request.user
        if event.status == EventStatus.DRAFT:
            allowed, reason = False, "drafts are not visible to ConnectSphere"
        elif user.role == Role.EVENT_COORDINATOR:
            allowed = event.coordinator_id == user.pk
            reason = "coordinator is not assigned to this event"
        else:  # Technical Support; HasAnyRole has refused every other role.
            allowed = EventRequest.objects.filter(pk=event.pk).filter(_has_open_requests()).exists()
            reason = "no equipment has been requested for this event"
        if not allowed:
            record_denied(user, action=f"{request.method} {request.path}", obj=event, detail=reason)
        return allowed


def _period(request, event):
    """The period to check: ``starts_at`` and ``ends_at`` from the query, both or
    neither; with neither, the event's preferred period (AC1)."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.utils.dateparse import parse_datetime
    from rest_framework.exceptions import ValidationError

    from apps.equipment.contracts import validate_period

    raw = {key: request.query_params.get(key, "").strip() for key in ("starts_at", "ends_at")}
    if bool(raw["starts_at"]) != bool(raw["ends_at"]):
        raise ValidationError({"period": ["Give both a start and an end, or neither."]})
    if raw["starts_at"]:
        try:
            starts_at, ends_at = parse_datetime(raw["starts_at"]), parse_datetime(raw["ends_at"])
        except ValueError:
            starts_at = ends_at = None
        if starts_at is None or ends_at is None:
            raise ValidationError({"period": ["Use ISO 8601 date-times with a time zone."]})
    else:
        starts_at, ends_at = event.preferred_start, event.preferred_end
        if starts_at is None or ends_at is None:
            raise ValidationError({"period": ["This event has no dates yet; choose a period."]})
    try:
        validate_period(starts_at, ends_at)
    except DjangoValidationError as exc:
        raise ValidationError({"period": exc.messages}) from None
    return starts_at, ends_at


class EventEquipmentAvailabilityView(APIView):
    """GET /api/events/<event_id>/equipment-availability/[?starts_at=&ends_at=]

    AC1-AC5 - every equipment type's available quantity for the period, what is
    unavailable and why, and the shortfall against this event's requests.
    """

    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, CanCheckEventAvailability]
    allowed_roles = frozenset({Role.TECHNICAL_SUPPORT, Role.EVENT_COORDINATOR})

    def get(self, request, event_id):
        from apps.equipment.services import availability_row

        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        starts_at, ends_at = _period(request, event)
        requested = {
            r.equipment_type_id: r.quantity
            for r in EquipmentRequest.objects.filter(plan__event=event).exclude(
                status=EquipmentRequestStatus.WITHDRAWN
            )
        }
        # Every offered type, plus any retired type this event still requests.
        types = EquipmentType.objects.filter(
            Q(in_service=True) | Q(pk__in=requested.keys())
        ).order_by("name", "pk")
        rows = [
            availability_row(t, starts_at, ends_at, requested=requested.get(t.pk), event=event)
            for t in types
        ]
        return Response(
            {
                "event": {
                    "id": event.pk,
                    "name": event.name,
                    "preferred_start": event.preferred_start,
                    "preferred_end": event.preferred_end,
                },
                "period": {"starts_at": starts_at, "ends_at": ends_at},
                "equipment": rows,
                # AC5 - every requested item that cannot be fully supplied.
                "shortfalls": [
                    {
                        "name": r["name"],
                        "requested": r["requested_quantity"],
                        "short_by": r["shortfall"],
                    }
                    for r in rows
                    if r["shortfall"]
                ],
            }
        )
