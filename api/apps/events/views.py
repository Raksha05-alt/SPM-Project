from rest_framework import mixins
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import Role
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest
from apps.events.serializers import EventRequestSerializer


class EventRequestViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, GenericViewSet):
    """US-02.1: create a request and list the current organisation's requests."""

    serializer_class = EventRequestSerializer
    permission_classes = [IsAuthenticated, HasAnyRole]
    allowed_roles = frozenset({Role.EVENT_ORGANISER})

    def get_queryset(self):
        return EventRequest.objects.select_related(
            "organisation", "created_by", "coordinator"
        ).filter(organisation_id=self.request.user.organisation_id)

    def perform_create(self, serializer):
        user = self.request.user
        if user.organisation_id is None:
            raise PermissionDenied("Your account is not linked to a client organisation.")
        serializer.save(created_by=user, organisation=user.organisation)
