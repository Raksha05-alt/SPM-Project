from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.permissions import HasAnyRole
from apps.venues.availability import availability
from apps.venues.block_serializers import (
    PeriodSerializer,
    VenueBlockHistorySerializer,
    VenueBlockSerializer,
)
from apps.venues.models import Venue, VenueBlockHistory
from apps.venues.serializers import VenueSerializer

CALENDAR_READERS = frozenset({Role.EVENT_COORDINATOR, Role.VENUE_STAFF})


class CalendarView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = CALENDAR_READERS

    def get(self, request, pk):
        venue = get_object_or_404(Venue, pk=pk)
        period = PeriodSerializer(data=request.query_params)
        period.is_valid(raise_exception=True)
        return Response(
            availability(
                venue, period.validated_data["starts_at"], period.validated_data["ends_at"]
            )
        )


class AvailableVenuesView(CalendarView):
    """SCRUM-13 AC3: period search; booking occupancy awaits its dependency."""

    def get(self, request):
        period = PeriodSerializer(data=request.query_params)
        period.is_valid(raise_exception=True)
        start, end = period.validated_data["starts_at"], period.validated_data["ends_at"]
        venues = [v for v in Venue.objects.all() if availability(v, start, end)["available"]]
        return Response(VenueSerializer(venues, many=True).data)


def snapshot(block, actor, action):
    VenueBlockHistory.objects.create(
        venue=block.venue,
        block_id=block.pk,
        reason=block.reason,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        actor=actor,
        action=action,
    )


class BlockView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]

    @property
    def allowed_roles(self):
        return CALENDAR_READERS if self.request.method in SAFE_METHODS else {Role.VENUE_STAFF}

    def get(self, request, pk):
        venue = get_object_or_404(Venue, pk=pk)
        return Response(VenueBlockSerializer(venue.blocks.all(), many=True).data)

    @transaction.atomic
    def post(self, request, pk):
        venue = get_object_or_404(Venue.objects.select_for_update(), pk=pk)
        serializer = VenueBlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        block = serializer.save(venue=venue)
        snapshot(block, request.user, "created")
        return Response(serializer.data, status=201)


class BlockDetailView(BlockView):
    http_method_names = ["patch", "delete", "options"]

    @transaction.atomic
    def patch(self, request, pk, block_pk):
        venue = get_object_or_404(Venue.objects.select_for_update(), pk=pk)
        block = get_object_or_404(venue.blocks, pk=block_pk)
        serializer = VenueBlockSerializer(block, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        block = serializer.save()
        snapshot(block, request.user, "updated")
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk, block_pk):
        venue = get_object_or_404(Venue.objects.select_for_update(), pk=pk)
        block = get_object_or_404(venue.blocks, pk=block_pk)
        snapshot(block, request.user, "removed")
        block.delete()
        return Response(status=204)


class BlockHistoryView(CalendarView):
    def get(self, request, pk):
        venue = get_object_or_404(Venue, pk=pk)
        return Response(
            VenueBlockHistorySerializer(venue.block_history.select_related("actor"), many=True).data
        )
