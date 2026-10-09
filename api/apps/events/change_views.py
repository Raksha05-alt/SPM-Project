"""SCRUM-20 / SCRUM-78 - change requests, from the client and to the coordinator."""

from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.change_requests import ChangeRefused, decide, raise_change_request
from apps.events.impact import impact_of
from apps.events.models import ChangeRequest, ChangeRequestStatus, EventRequest
from apps.events.serializers import ChangeRequestSerializer, DecisionInputSerializer
from apps.events.services import NotAssignedCoordinator

CHANGE_ROLES = frozenset({Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR})


def check_access(request, event: EventRequest, action_name: str) -> None:
    """The client's own organisation, or ConnectSphere coordinators for submitted events."""
    user = request.user
    if user.role == Role.EVENT_ORGANISER and event.organisation_id == user.organisation_id:
        return
    if user.role == Role.EVENT_COORDINATOR and event.status != EventStatus.DRAFT:
        return
    record_denied(user, action=action_name, obj=event, detail="no access to this event")
    raise PermissionDenied("You do not have access to this event.")


class EventChangeRequestsView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = CHANGE_ROLES

    def get(self, request, event_id):
        """SCRUM-20 AC5 - the event's change requests with their status and decisions."""
        event = get_object_or_404(EventRequest, pk=event_id)
        check_access(request, event, f"GET /api/events/{event_id}/change-requests/")
        changes = event.change_requests.select_related("requested_by", "decided_by")
        return Response(ChangeRequestSerializer(changes, many=True).data)

    def post(self, request, event_id):
        """SCRUM-20 AC1-AC4 - the client asks for a change."""
        action_name = f"POST /api/events/{event_id}/change-requests/"
        event = get_object_or_404(EventRequest, pk=event_id)
        check_access(request, event, action_name)
        if request.user.role != Role.EVENT_ORGANISER:
            record_denied(request.user, action=action_name, obj=event, detail="clients only")
            raise PermissionDenied("Only the client can request a change to an event.")
        serializer = ChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            change = raise_change_request(event, request.user, dict(serializer.validated_data))
        except ChangeRefused as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        record(request.user, action_name, allowed=True, obj=change)
        return Response(ChangeRequestSerializer(change).data, status=http.HTTP_201_CREATED)


class ChangeRequestDetailView(APIView):
    """SCRUM-78 AC1-AC4 - a change request with its impact, for the coordinator."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = CHANGE_ROLES

    def get(self, request, pk):
        change = get_object_or_404(ChangeRequest.objects.select_related("event"), pk=pk)
        check_access(request, change.event, f"GET /api/change-requests/{pk}/")
        data = ChangeRequestSerializer(change).data
        if request.user.role == Role.EVENT_COORDINATOR and (
            change.status == ChangeRequestStatus.PENDING
        ):
            data["impact"] = impact_of(change.event, change.proposed_values())
        return Response(data)


class ChangeDecisionView(APIView):
    """SCRUM-78 AC5 - approve or reject with a reason."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})
    approve = True

    def post(self, request, pk):
        change = get_object_or_404(ChangeRequest.objects.select_related("event"), pk=pk)
        verb = "approve" if self.approve else "reject"
        action_name = f"POST /api/change-requests/{pk}/{verb}/"
        payload = DecisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            change = decide(
                change, request.user, approve=self.approve, reason=payload.validated_data["reason"]
            )
        except NotAssignedCoordinator:
            record_denied(
                request.user, action=action_name, obj=change, detail="not the assigned coordinator"
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can decide on its changes."
            ) from None
        except ChangeRefused as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        record(request.user, action_name, allowed=True, obj=change)
        return Response(ChangeRequestSerializer(change).data)
