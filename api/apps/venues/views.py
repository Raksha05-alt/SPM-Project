from django.db import transaction
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.audit import record
from apps.core.permissions import HasAnyRole
from apps.venues.models import Venue
from apps.venues.permissions import VENUE_EDITORS, VENUE_READERS
from apps.venues.serializers import VenueSerializer


class VenueViewSet(ModelViewSet):
    """SCRUM-65 - Venue Staff create and update venue records."""

    serializer_class = VenueSerializer
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated]
    # Venue records are kept, so there is no delete.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    queryset = Venue.objects.select_related("created_by", "updated_by")

    @property
    def allowed_roles(self):
        if self.request.method in SAFE_METHODS:
            return VENUE_READERS
        return VENUE_EDITORS

    def perform_create(self, serializer):
        user = self.request.user
        venue = serializer.save(created_by=user, updated_by=user)
        record(user, "POST /api/venues/", allowed=True, obj=venue)

    def update(self, request, *args, **kwargs):
        partial = kwargs.get("partial", False)
        action_name = f"{request.method} /api/venues/{kwargs['pk']}/"
        with transaction.atomic():
            venue = Venue.objects.select_for_update().get(pk=self.get_object().pk)
            serializer = self.get_serializer(venue, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            # AC2 - who changed it; updated_at records when.
            venue = serializer.save(updated_by=request.user)
            record(request.user, action_name, allowed=True, obj=venue)
        return Response(self.get_serializer(venue).data)
