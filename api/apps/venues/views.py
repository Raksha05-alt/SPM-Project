from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.audit import record
from apps.core.permissions import HasAnyRole
from apps.venues.layouts import (
    LayoutChoiceError,
    bookings_affected_by_removal,
    cached_label_map,
    claim_layouts,
)
from apps.venues.models import LayoutType, Venue
from apps.venues.permissions import VENUE_EDITORS, VENUE_READERS
from apps.venues.serializers import VenueSerializer


def _layout_removal_warning(venue, removed, affected, context):
    """INT-02 - the 409 body naming every approved booking that uses a removed layout."""
    labels = cached_label_map(context)
    names = ", ".join(labels.get(code, code) for code in removed)
    count = len(affected)
    noun = "booking" if count == 1 else "bookings"
    return {
        "detail": (
            f"Removing {names} from {venue.name} affects {count} approved {noun}. "
            f"The {noun} will be kept. Confirm to remove the layout anyway."
        ),
        "affected_bookings": [
            {
                "booking": booking.pk,
                "event": booking.event_id,
                "event_name": booking.event.name,
                "layout": booking.layout,
                "layout_name": labels.get(booking.layout, booking.layout),
                "starts_at": booking.starts_at,
                "ends_at": booking.ends_at,
            }
            for booking in affected
        ],
    }


def _claim_venue_layouts(validated_data, *, keep):
    """SCRUM-91 - recheck chosen layouts under a catalogue row lock before saving."""
    if "layouts" in validated_data:
        try:
            claim_layouts(validated_data["layouts"], keep=keep)
        except LayoutChoiceError as exc:
            raise ValidationError({"layouts": [exc.message]}) from None


class VenueViewSet(ModelViewSet):
    """SCRUM-65 - Venue Staff create and update venue records."""

    serializer_class = VenueSerializer
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated]
    # Venue records are kept, so there is no delete.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    queryset = Venue.objects.select_related("created_by", "updated_by")

    def get_queryset(self):
        queryset = super().get_queryset()
        layout = self.request.query_params.get("layout")
        if self.action == "list" and layout:
            # SCRUM-5 AC3 - a venue with the layout recorded is eligible to appear.
            if not LayoutType.objects.filter(code=layout).exists():
                raise ValidationError({"layout": "Unknown layout."})
            queryset = queryset.supporting_layout(layout)
        return queryset

    @property
    def allowed_roles(self):
        if self.request.method in SAFE_METHODS:
            return VENUE_READERS
        return VENUE_EDITORS

    def perform_create(self, serializer):
        user = self.request.user
        with transaction.atomic():
            _claim_venue_layouts(serializer.validated_data, keep=[])
            venue = serializer.save(created_by=user, updated_by=user)
        record(user, "POST /api/venues/", allowed=True, obj=venue)

    def update(self, request, *args, **kwargs):
        partial = kwargs.get("partial", False)
        action_name = f"{request.method} /api/venues/{kwargs['pk']}/"
        with transaction.atomic():
            venue = Venue.objects.select_for_update().get(pk=self.get_object().pk)
            serializer = self.get_serializer(venue, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            _claim_venue_layouts(serializer.validated_data, keep=venue.layouts)
            # INT-02 (SCRUM-5 AC4) - removing a layout that approved bookings use
            # needs an explicit confirmation. The bookings are kept either way.
            # The venue row lock above also serialises this with approvals.
            new_layouts = serializer.validated_data.get("layouts", venue.layouts)
            removed = [code for code in venue.layouts if code not in new_layouts]
            affected = bookings_affected_by_removal(venue, removed)
            if affected and request.data.get("confirm_layout_removal") is not True:
                return Response(
                    _layout_removal_warning(
                        venue, removed, affected, self.get_serializer_context()
                    ),
                    status=status.HTTP_409_CONFLICT,
                )
            # AC2 - who changed it; updated_at records when.
            venue = serializer.save(updated_by=request.user)
            detail = ""
            if affected:
                detail = "Layout removed; approved bookings kept: " + ", ".join(
                    str(booking.pk) for booking in affected
                )
            record(request.user, action_name, allowed=True, obj=venue, detail=detail)
        return Response(self.get_serializer(venue).data)
