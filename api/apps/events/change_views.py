"""SCRUM-20 - Request a change to an event (Sprint 4 gate INTAKE).

GET  /api/events/<event_id>/change-requests/   the event's change requests (AC5)
POST /api/events/<event_id>/change-requests/   the organiser requests a change (AC1)

Readers: the event's own organisation, its assigned coordinator and Leads.
Every refusal is audited.
"""

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
from apps.events.change_requests import ChangeRequestError, NotEventOrganiser, request_change
from apps.events.history_views import _display
from apps.events.models import EventChangeRequest, EventRequest
from apps.venues.layouts import cached_label_map


def _name(user):
    return None if user is None else (user.get_full_name() or user.email)


class ChangeRequestSerializer(serializers.ModelSerializer):
    """AC5 - the request, its current status and any decision."""

    requested_by_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    proposed_changes = serializers.SerializerMethodField()

    class Meta:
        model = EventChangeRequest
        fields = [
            "id",
            "event",
            "description",
            "reason",
            "proposed_values",
            "proposed_changes",
            "target_bookings",
            "target_equipment_requests",
            "revision",
            "status",
            "status_label",
            "status_changed_at",
            "requested_by_name",
            "requested_at",
            "decided_by_name",
            "decided_at",
            "decision_reason",
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj):
        return _name(obj.decided_by)

    def get_proposed_changes(self, obj) -> list[dict]:
        """Each proposed field with its value at request time and the new value, readable."""
        labels = cached_label_map(self.context)
        rows = []
        for field, value in obj.proposed_values.items():
            label = str(EventRequest._meta.get_field(field).verbose_name).capitalize()
            rows.append(
                {
                    "field": field,
                    "label": label,
                    "current": _display(field, obj.source_values.get(field), labels),
                    "proposed": _display(field, value, labels),
                }
            )
        return rows


class ChangeRequestInputSerializer(serializers.Serializer):
    """Parses the request without coercion; the service names every problem."""

    description = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.JSONField(required=False, allow_null=True)
    proposed_values = serializers.JSONField(required=False, allow_null=True)
    target_bookings = serializers.JSONField(required=False, allow_null=True)
    target_equipment_requests = serializers.JSONField(required=False, allow_null=True)


class CanSeeChangeRequests(BasePermission):
    """The event's own organisation, its assigned coordinator, or a Lead."""

    message = "You do not have access to this event's change requests."

    def has_object_permission(self, request, view, event):
        user = request.user
        if user.role == Role.EVENT_ORGANISER:
            allowed = event.organisation_id == user.organisation_id
            reason = "event belongs to another client organisation"
        elif event.status == EventStatus.DRAFT:
            allowed, reason = False, "drafts are not visible to ConnectSphere"
        elif user.role == Role.EVENT_COORDINATOR:
            allowed = event.coordinator_id == user.pk
            reason = "coordinator is not assigned to this event"
        else:
            allowed, reason = True, ""
        if not allowed:
            record_denied(user, action=f"{request.method} {request.path}", obj=event, detail=reason)
        return allowed


class EventChangeRequestsView(APIView):
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, CanSeeChangeRequests]

    @property
    def allowed_roles(self):
        if self.request.method == "POST":
            return frozenset({Role.EVENT_ORGANISER})
        return frozenset(
            {Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD}
        )

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        changes = (
            EventChangeRequest.objects.filter(event=event)
            .select_related("requested_by", "decided_by")
            .order_by("-requested_at", "-pk")
        )
        return Response(ChangeRequestSerializer(changes, many=True).data)

    def post(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        payload = ChangeRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            change = request_change(
                event=event, requested_by=request.user, **payload.validated_data
            )
        except NotEventOrganiser:
            record_denied(
                request.user,
                action=f"POST /api/events/{event_id}/change-requests/",
                obj=event,
                detail="only the event's own organisation may request a change",
            )
            raise PermissionDenied("You can only request changes to your own events.") from None
        except ChangeRequestError as exc:
            return Response(
                {
                    "detail": "The change request could not be sent.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                # AC2 - the receipt: Pending, and who will review it.
                "detail": (
                    "Your change request has been sent and is Pending review."
                    if event.coordinator_id
                    else "Your change request has been sent to ConnectSphere and is Pending review."
                ),
                "change_request": ChangeRequestSerializer(change).data,
            },
            status=status.HTTP_201_CREATED,
        )
