from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.statuses import InvalidTransition
from apps.events.permissions import CanAccessEventRequest
from apps.events.services import MissingMandatoryFields, submit_event
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import Role
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest
from apps.events.serializers import EventRequestSerializer


class EventRequestViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, GenericViewSet):
    """US-02.1/US-02.2: create, open and submit organisation requests."""

    serializer_class = EventRequestSerializer
    permission_classes = [IsAuthenticated, HasAnyRole, CanAccessEventRequest]
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

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        event = self.get_object()
        try:
            submit_event(event, request.user)
        except MissingMandatoryFields as exc:
            return Response({"detail": "This request cannot be submitted yet.",
                             "missing_fields": exc.fields}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(event).data)
