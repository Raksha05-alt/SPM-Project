"""SCRUM-71 - the suitability check an Event Coordinator runs for an event."""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest, EventStatus
from apps.venues.models import Venue
from apps.venues.suitability import check_suitability, clean_facilities


def required_facilities(request) -> list[str]:
    """Accept ``?facilities=a&facilities=b`` or ``?facilities=a,b``."""
    names = []
    for value in request.query_params.getlist("facilities"):
        names.extend(value.split(","))
    return clean_facilities(names)


class EventVenueSuitabilityView(APIView):
    """Check one venue, or every venue, against an event's requirements."""

    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def get(self, request, event_id, venue_id=None):
        # A coordinator never sees drafts (US-03.1 AC4), so neither does this check.
        event = get_object_or_404(
            EventRequest.objects.exclude(status=EventStatus.DRAFT), pk=event_id
        )
        facilities = required_facilities(request)
        if venue_id is not None:
            venue = get_object_or_404(Venue, pk=venue_id)
            return Response(check_suitability(event, venue, facilities).as_dict())
        results = [check_suitability(event, v, facilities).as_dict() for v in Venue.objects.all()]
        return Response({"event": event.pk, "required_facilities": facilities, "venues": results})
