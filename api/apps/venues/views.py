from django.db import transaction
from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.events.models import RoomLayout
from apps.venues.models import BookingStatus, Venue
from apps.venues.permissions import INTERNAL_ROLES
from apps.venues.serializers import VenueSerializer


def require_venue_staff(request, action: str, obj=None):
    if request.user.role != Role.VENUE_STAFF:
        record_denied(request.user, action=action, obj=obj, detail="venue staff only")
        raise PermissionDenied("Only Venue Staff can change venue records.")


class VenueViewSet(ModelViewSet):
    """SCRUM-65 maintain, SCRUM-9 view and SCRUM-5 layouts/facilities of venues."""

    serializer_class = VenueSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = INTERNAL_ROLES
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        return Venue.objects.select_related("updated_by").prefetch_related("blocks")

    def perform_create(self, serializer):
        require_venue_staff(self.request, "POST /api/venues/")
        venue = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        record(self.request.user, "POST /api/venues/", allowed=True, obj=venue)

    def update(self, request, *args, **kwargs):
        venue = self.get_object()
        action = f"{request.method} /api/venues/{venue.pk}/"
        require_venue_staff(request, action, venue)
        serializer = self.get_serializer(venue, data=request.data, partial=kwargs.get("partial"))
        serializer.is_valid(raise_exception=True)

        # SCRUM-5 AC4 - removing a layout that a confirmed booking relies on.
        removed = set(venue.layouts) - set(serializer.validated_data.get("layouts", venue.layouts))
        affected = list(
            venue.bookings.filter(
                status=BookingStatus.APPROVED, layout__in=removed, end__gt=timezone.now()
            ).select_related("event")
        )
        if affected and not request.data.get("confirm_layout_removal"):
            return Response(
                {
                    "detail": "Confirmed bookings use a layout you are removing.",
                    "affected_bookings": [
                        {
                            "id": booking.pk,
                            "event": booking.event_id,
                            "event_name": booking.event.name,
                            "layout": RoomLayout(booking.layout).label,
                            "start": booking.start,
                            "end": booking.end,
                        }
                        for booking in affected
                    ],
                },
                status=http.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            serializer.save(updated_by=request.user)
            for booking in affected:
                booking.review_required = True
                booking.review_reason = f"{venue.name} no longer supports the {RoomLayout(booking.layout).label} layout."
                booking.review_flagged_at = timezone.now()
                booking.save(
                    update_fields=["review_required", "review_reason", "review_flagged_at"]
                )
        record(request.user, action, allowed=True, obj=venue)
        return Response(serializer.data)
