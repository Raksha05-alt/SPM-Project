from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest
from apps.venues.availability import availability, comparison_availability
from apps.venues.block_serializers import (
    PeriodSerializer,
    VenueBlockHistorySerializer,
    VenueBlockSerializer,
)
from apps.venues.bookings import disrupt_bookings
from apps.venues.models import Venue, VenueBlockHistory, VenueBooking
from apps.venues.occupancy import occupancy_prefetch
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
    """SCRUM-13/G12: period search through the shared booking/block checks."""

    def get(self, request):
        period = PeriodSerializer(data=request.query_params)
        period.is_valid(raise_exception=True)
        start, end = period.validated_data["starts_at"], period.validated_data["ends_at"]
        venues = [v for v in Venue.objects.all() if availability(v, start, end)["available"]]
        return Response(VenueSerializer(venues, many=True).data)


class CompareAvailabilityView(CalendarView):
    """SCRUM-62: all venues, including partially and wholly obstructed rooms."""

    def get(self, request):
        period = PeriodSerializer(data=request.query_params)
        period.is_valid(raise_exception=True)
        start, end = period.validated_data["starts_at"], period.validated_data["ends_at"]
        venues = Venue.objects.order_by("name", "pk").prefetch_related(
            "blocks", occupancy_prefetch()
        )
        results = [comparison_availability(venue, start, end) for venue in venues]
        return Response(
            {
                "starts_at": start,
                "ends_at": end,
                "venues": results,
                "message": ""
                if any(v["available"] for v in results)
                else "No venues are available for the whole period.",
            }
        )


def snapshot(block, actor, action):
    VenueBlockHistory.objects.create(
        venue=block.venue,
        block_id=block.pk,
        reason=block.reason,
        reason_category=block.reason_category,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        actor=actor,
        action=action,
    )


class _MembershipChanged(Exception):
    pass


def _lock_block_events(venue_id):
    ids = set(VenueBooking.objects.filter(venue_id=venue_id).values_list("event_id", flat=True))
    list(EventRequest.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    venue = get_object_or_404(Venue.objects.select_for_update(), pk=venue_id)
    current = set(VenueBooking.objects.filter(venue_id=venue_id).values_list("event_id", flat=True))
    if not current.issubset(ids):
        raise _MembershipChanged
    return venue


class BlockView(APIView):
    def dispatch(self, request, *args, **kwargs):
        for attempt in range(5):
            try:
                return super().dispatch(request, *args, **kwargs)
            except _MembershipChanged:
                if attempt == 4:
                    return Response(
                        {"detail": "Bookings changed concurrently. Please retry."}, status=409
                    )

    permission_classes = [HasAnyRole, IsAuthenticated]

    @property
    def allowed_roles(self):
        return CALENDAR_READERS if self.request.method in SAFE_METHODS else {Role.VENUE_STAFF}

    def get(self, request, pk):
        venue = get_object_or_404(Venue, pk=pk)
        return Response(
            VenueBlockSerializer(venue.blocks.all(), many=True, context={"request": request}).data
        )

    @transaction.atomic
    def post(self, request, pk):
        venue = _lock_block_events(pk)
        serializer = VenueBlockSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        block = serializer.save(venue=venue)
        snapshot(block, request.user, "created")
        disrupt_bookings(block, request.user)
        return Response(serializer.data, status=201)


class BlockDetailView(BlockView):
    http_method_names = ["patch", "delete", "options"]

    @transaction.atomic
    def patch(self, request, pk, block_pk):
        venue = _lock_block_events(pk)
        block = get_object_or_404(venue.blocks, pk=block_pk)
        serializer = VenueBlockSerializer(
            block, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        block = serializer.save()
        snapshot(block, request.user, "updated")
        disrupt_bookings(block, request.user)
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk, block_pk):
        venue = _lock_block_events(pk)
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
