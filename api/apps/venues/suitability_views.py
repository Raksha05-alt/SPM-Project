"""SCRUM-71 - the suitability check an Event Coordinator runs for their event.

GET /api/events/<event_id>/venue-suitability/              every venue
GET /api/events/<event_id>/venue-suitability/<venue_id>/   one venue

Query parameters:
  facilities   required facility names, repeated or comma separated
  wheelchair   "true" when step-free wheelchair access is required

Only the event's currently assigned coordinator may run it (SCRUM-89
ownership); drafts are never visible to ConnectSphere. Every refusal is audited.
"""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.venues.layouts import label_map
from apps.venues.models import Venue
from apps.venues.suitability import Requirements, assess, clean_facilities

# Stated with every response so the result is never read as "this room is free".
NOT_CHECKED = [
    "Whether the venue is free: bookings, blocks and operational status are checked "
    "separately (venue availability).",
]


class IsAssignedCoordinator(BasePermission):
    """The event's current coordinator only; drafts are never visible (US-03.1 AC4)."""

    message = "Only the coordinator assigned to this event can check venue suitability."

    def has_object_permission(self, request, view, event):
        allowed = event.status != EventStatus.DRAFT and event.coordinator_id == request.user.pk
        if not allowed:
            record_denied(
                request.user,
                action=f"{request.method} {request.path}",
                obj=event,
                detail="draft event or coordinator is not assigned to this event",
            )
        return allowed


def required_facilities(request) -> list[str]:
    """Accept ``?facilities=a&facilities=b`` or ``?facilities=a,b``."""
    names = []
    for value in request.query_params.getlist("facilities"):
        names.extend(value.split(","))
    return clean_facilities(names)


def wheelchair_required(request) -> bool:
    value = request.query_params.get("wheelchair", "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValidationError({"wheelchair": ["Use true or false."]})
    return value == "true"


class EventVenueSuitabilityView(APIView):
    """Check one venue, or every venue, against the event's requirements."""

    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, IsAssignedCoordinator]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def get(self, request, event_id, venue_id=None):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        requirements = Requirements.for_event(
            event,
            required_facilities=required_facilities(request),
            wheelchair_access_required=wheelchair_required(request),
        )
        labels = label_map()
        if venue_id is not None:
            venue = get_object_or_404(Venue, pk=venue_id)
            return Response(self._result(venue, requirements, labels))
        return Response(
            {
                "event": event.pk,
                "requirements": requirements.as_dict(labels),
                "not_checked": NOT_CHECKED,
                "venues": [self._result(v, requirements, labels) for v in Venue.objects.all()],
            }
        )

    @staticmethod
    def _result(venue, requirements, labels) -> dict:
        result = assess(venue, requirements, labels=labels).as_dict()
        # Shown beside the result, never as a suitability reason.
        result["in_service"] = venue.in_service
        return result
