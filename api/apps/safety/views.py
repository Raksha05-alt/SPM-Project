"""Week 7 change 6 - the Operational Safety Check endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest
from apps.events.services import NotAssignedCoordinator, NotPermitted
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.serializers import (
    SafetyCheckSerializer,
    SafetyDecisionInputSerializer,
    SafetyRequestInputSerializer,
)
from apps.safety.services import SafetyRefused, decide, request_check

READERS = frozenset({Role.SAFETY_OFFICER, Role.EVENT_COORDINATOR, Role.COORDINATOR_LEAD})


def refused(exc: SafetyRefused) -> Response:
    return Response({"detail": exc.detail, **exc.extra}, status=exc.status)


class SafetyCheckViewSet(ReadOnlyModelViewSet):
    """Safety Officers see every check (pending first); a coordinator sees the checks of
    their own events; Leads see all. ``?status=PENDING`` narrows the list."""

    serializer_class = SafetyCheckSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = READERS

    def get_queryset(self):
        checks = SafetyCheck.objects.select_related(
            "event", "event__organisation", "event__coordinator", "requested_by", "decided_by"
        )
        user = self.request.user
        if user.is_coordinator:
            checks = checks.filter(event__coordinator=user)
        wanted = self.request.query_params.get("status")
        if wanted:
            values = [v for v in wanted.split(",") if v]
            unknown = [v for v in values if v not in SafetyStatus.values]
            if unknown:
                raise ValidationError({"status": [f"Unknown status: {', '.join(unknown)}."]})
            checks = checks.filter(status__in=values)
        return checks

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        check = self.get_object()
        action_name = f"POST /api/safety-checks/{check.pk}/decide/"
        payload = SafetyDecisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            result = decide(
                check,
                request.user,
                payload.validated_data["decision"],
                payload.validated_data["comment"],
            )
        except NotPermitted:
            # The service owns the rule; the view records the refusal.
            record_denied(
                request.user, action=action_name, obj=check, detail="safety officers only"
            )
            raise PermissionDenied("Only a Safety Officer can decide a safety check.") from None
        except SafetyRefused as exc:
            return refused(exc)
        record(request.user, action_name, allowed=True, obj=result)
        return Response(SafetyCheckSerializer(result).data)


class EventSafetyChecksView(APIView):
    """GET - every check on the event, newest first. POST - the coordinator requests one."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = READERS

    def _event(self, request, event_id) -> EventRequest:
        event = get_object_or_404(EventRequest, pk=event_id)
        user = request.user
        if user.is_coordinator and event.coordinator_id != user.pk:
            record_denied(
                user, action=f"{request.method} {request.path}", obj=event, detail="not assigned"
            )
            raise PermissionDenied("Only the coordinator assigned to this event can do this.")
        return event

    def get(self, request, event_id):
        event = self._event(request, event_id)
        checks = event.safety_checks.select_related("event", "requested_by", "decided_by")
        return Response(SafetyCheckSerializer(checks, many=True).data)

    def post(self, request, event_id):
        action_name = f"POST /api/events/{event_id}/safety-checks/"
        if not request.user.is_coordinator:
            record_denied(request.user, action=action_name, detail="coordinators only")
            raise PermissionDenied("Only the event's coordinator can request a safety check.")
        event = self._event(request, event_id)
        payload = SafetyRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            check = request_check(event, request.user, payload.validated_data["note"])
        except NotAssignedCoordinator:
            raise PermissionDenied(
                "Only the coordinator assigned to this event can do this."
            ) from None
        except SafetyRefused as exc:
            return refused(exc)
        record(request.user, action_name, allowed=True, obj=check)
        return Response(SafetyCheckSerializer(check).data, status=http.HTTP_201_CREATED)
