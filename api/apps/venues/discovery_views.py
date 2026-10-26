from contextlib import contextmanager

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import TERMINAL_STATUSES
from apps.events.models import EventRequest
from apps.venues.discovery import (
    AVAILABILITY_LIMITATION,
    add_to_shortlist,
    remove_from_shortlist,
    search_venues,
)
from apps.venues.discovery_permissions import CanAccessVenueShortlist
from apps.venues.discovery_serializers import (
    AddShortlistSerializer,
    VenueMatchSerializer,
    VenueSearchCriteriaSerializer,
    VenueShortlistEntrySerializer,
)
from apps.venues.models import VenueShortlistEntry


class VenueSearchView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def get(self, request):
        data = {key: value for key, value in request.query_params.items() if value != ""}
        data["facilities"] = [
            item for item in request.query_params.getlist("facilities") if item.strip()
        ]
        serializer = VenueSearchCriteriaSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        criteria = dict(serializer.data)
        results = VenueMatchSerializer(search_venues(criteria), many=True).data
        return Response(
            {
                "results": results,
                "criteria": criteria,
                "availability_integrated": False,
                "date_blocks_integrated": True,
                "limitation": AVAILABILITY_LIMITATION,
            }
        )


class EventVenueShortlistView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated, CanAccessVenueShortlist]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def event(self, request, event_id, *, lock=False):
        queryset = EventRequest.objects.select_for_update() if lock else EventRequest.objects.all()
        event = get_object_or_404(queryset, pk=event_id)
        self.check_object_permissions(request, event)
        return event

    @contextmanager
    def locked_event(self, request, event_id):
        try:
            with transaction.atomic():
                yield self.event(request, event_id, lock=True)
        except PermissionDenied:
            # The permission class's audit insert rolled back with the refused
            # mutation. Keep the refusal after releasing the transaction.
            record_denied(
                request.user,
                action=f"{request.method} {request.path}",
                detail="shortlist write permission refused",
            )
            raise

    def get(self, request, event_id):
        event = self.event(request, event_id)
        entries = event.venue_shortlist.select_related(
            "event", "venue__created_by", "venue__updated_by"
        ).prefetch_related("venue__blocks")
        return Response(
            {
                "event_id": event.pk,
                "can_edit": event.coordinator_id == request.user.pk
                and event.status not in TERMINAL_STATUSES,
                "entries": VenueShortlistEntrySerializer(entries, many=True).data,
                "availability_integrated": False,
                "date_blocks_integrated": True,
                "limitation": AVAILABILITY_LIMITATION,
            }
        )

    def post(self, request, event_id):
        with self.locked_event(request, event_id) as event:
            serializer = AddShortlistSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            criteria = dict(VenueSearchCriteriaSerializer(data.get("criteria", {})).data)
            entry, created = add_to_shortlist(event, data["venue"], criteria, request.user)
            return Response(
                VenueShortlistEntrySerializer(entry).data, status=201 if created else 200
            )


class EventVenueShortlistItemView(EventVenueShortlistView):
    http_method_names = ["delete", "options"]

    def delete(self, request, event_id, venue_id):
        with self.locked_event(request, event_id) as event:
            entry = get_object_or_404(VenueShortlistEntry, event=event, venue_id=venue_id)
            remove_from_shortlist(event, entry, request.user)
            return Response(status=204)
