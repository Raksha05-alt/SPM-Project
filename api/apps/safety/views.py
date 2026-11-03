"""SCRUM-90 - Operational Safety Check endpoints.

GET  /api/safety-checks/                 Safety Officers and Leads: every check;
                                         coordinators: their events' checks.
GET  /api/safety-checks/<id>/            one check with the facts to review (AC2)
POST /api/safety-checks/<id>/decide/     Safety Officers only (AC3, AC7)
GET  /api/events/<id>/safety-checks/     the event's checks, arrangement_gaps and
                                         confirmation_gaps
POST /api/events/<id>/safety-checks/     the assigned coordinator requests a check (AC1)

Event Organisers, Attendees, Venue Staff and Technical Support are refused by
HasAnyRole, which also writes the audit row (AC7).
"""

from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.events.services import NotAssignedCoordinator
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.serializers import (
    SafetyCheckDetailSerializer,
    SafetyCheckSerializer,
    SafetyDecisionInputSerializer,
    SafetyRequestInputSerializer,
)
from apps.safety.services import (
    NotSafetyOfficer,
    SafetyRefused,
    arrangement_gaps,
    confirmation_gaps,
    current_check,
    decide,
    is_stale,
    request_check,
)

READERS = frozenset({Role.SAFETY_OFFICER, Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD})


def refused(exc: SafetyRefused) -> Response:
    return Response({"detail": exc.detail, **exc.extra}, status=exc.status)


class SafetyCheckViewSet(ReadOnlyModelViewSet):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = READERS

    def get_serializer_class(self):
        return SafetyCheckSerializer if self.action == "list" else SafetyCheckDetailSerializer

    def get_queryset(self):
        checks = SafetyCheck.objects.select_related(
            "event",
            "event__organisation",
            "event__coordinator",
            "requested_by",
            "decided_by",
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

    def get_object(self):
        """Look across every check so a coordinator reaching for another
        coordinator's check is refused and audited rather than given a 404."""
        check = get_object_or_404(
            SafetyCheck.objects.select_related(
                "event", "event__organisation", "event__coordinator", "requested_by", "decided_by"
            ),
            pk=self.kwargs["pk"],
        )
        user = self.request.user
        if user.is_coordinator and check.event.coordinator_id != user.pk:
            record_denied(
                user,
                action=f"{self.request.method} {self.request.path}",
                obj=check,
                detail="event is not assigned to this coordinator",
            )
            raise PermissionDenied("This safety check belongs to another coordinator's event.")
        return check

    @action(detail=True, methods=["post"], allowed_roles=frozenset({Role.SAFETY_OFFICER}))
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
        except NotSafetyOfficer:
            record_denied(
                request.user, action=action_name, obj=check, detail="only a Safety Officer"
            )
            raise PermissionDenied("Only a Safety Officer can decide a safety check.") from None
        except SafetyRefused as exc:
            record_denied(request.user, action=action_name, obj=check, detail=exc.detail)
            return refused(exc)
        return Response(SafetyCheckDetailSerializer(result).data)


class EventSafetyChecksView(APIView):
    """The event's checks, newest first, with what stands between it and confirmation."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = READERS

    def _event(self, request, event_id) -> EventRequest:
        event = get_object_or_404(
            EventRequest.objects.select_related("organisation", "coordinator"), pk=event_id
        )
        user = request.user
        if user.is_coordinator and event.coordinator_id != user.pk:
            record_denied(
                user,
                action=f"{request.method} {request.path}",
                obj=event,
                detail="event is not assigned to this coordinator",
            )
            raise PermissionDenied("Only the coordinator assigned to this event can do this.")
        return event

    def get(self, request, event_id):
        event = self._event(request, event_id)
        checks = event.safety_checks.select_related(
            "event", "event__organisation", "event__coordinator", "requested_by", "decided_by"
        )
        gaps = arrangement_gaps(event)
        existing = current_check(event)
        return Response(
            {
                "checks": SafetyCheckSerializer(checks, many=True).data,
                "arrangement_gaps": gaps,
                "confirmation_gaps": confirmation_gaps(event),
                # A new check is possible when there is none standing, or the
                # standing one no longer matches the arrangements.
                "can_request": (
                    event.status == EventStatus.PLANNING
                    and not gaps
                    and (existing is None or is_stale(existing, event))
                ),
            }
        )

    def post(self, request, event_id):
        action_name = f"POST /api/events/{event_id}/safety-checks/"
        if not request.user.is_coordinator:
            record_denied(request.user, action=action_name, detail="only the assigned coordinator")
            raise PermissionDenied("Only the event's coordinator can request a safety check.")
        event = self._event(request, event_id)
        payload = SafetyRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            check = request_check(event, request.user, payload.validated_data["note"])
        except NotAssignedCoordinator:
            # Reassigned between the view's check and the service's locked reread.
            record_denied(
                request.user, action=action_name, obj=event, detail="no longer the coordinator"
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can do this."
            ) from None
        except SafetyRefused as exc:
            record_denied(request.user, action=action_name, obj=event, detail=exc.detail)
            return refused(exc)
        return Response(SafetyCheckDetailSerializer(check).data, status=http.HTTP_201_CREATED)
