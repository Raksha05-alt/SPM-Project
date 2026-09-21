from rest_framework import status as http
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import INTERNAL_STATUSES, EventStatus, InvalidTransition, describe
from apps.events.models import EventRequest
from apps.events.permissions import CanAccessEventRequest
from apps.events.serializers import EventQueueSerializer, EventRequestSerializer
from apps.events.services import MissingMandatoryFields, submit_event

QUEUE_EXCLUDED = (EventStatus.DRAFT, EventStatus.REJECTED)


class EventRequestViewSet(ModelViewSet):
    serializer_class = EventRequestSerializer
    permission_classes = [IsAuthenticated, HasAnyRole, CanAccessEventRequest]
    allowed_roles = frozenset({Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR})

    def get_queryset(self):
        user = self.request.user
        base = EventRequest.objects.select_related("organisation", "created_by", "coordinator")
        if user.role == Role.EVENT_ORGANISER:
            # US-02.3 / US-03.1 AC5 - a client sees only their own organisation.
            return base.filter(organisation_id=user.organisation_id)
        if user.role == Role.EVENT_COORDINATOR:
            # US-03.1 AC4 - drafts never reach ConnectSphere.
            return base.exclude(status=EventStatus.DRAFT)
        return base.none()

    def get_object(self):
        """Look the object up across all rows so that a cross-organisation attempt
        is refused and audited (US-01.2 AC1) rather than silently returning 404."""
        obj = (
            EventRequest.objects.select_related("organisation", "created_by", "coordinator")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if obj is None:
            from django.http import Http404

            raise Http404
        self.check_object_permissions(self.request, obj)
        return obj

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_organiser:
            record_denied(
                user, action="POST /api/events/", detail="only a client may raise a request"
            )
            raise PermissionDenied("Only an Event Organiser can create an event request.")
        if user.organisation_id is None:
            raise PermissionDenied("Your account is not linked to a client organisation.")
        serializer.save(created_by=user, organisation=user.organisation)

    def perform_destroy(self, instance):
        # US-03.1 AC6 - a draft may be deleted; anything submitted may not.
        if not instance.is_draft:
            record_denied(
                self.request.user,
                action=f"DELETE /api/events/{instance.pk}/",
                obj=instance,
                detail="only a draft may be deleted",
            )
            raise PermissionDenied("Only a draft can be deleted.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """US-02.2 - submit a draft for review."""
        event = self.get_object()
        try:
            submit_event(event, request.user)
        except MissingMandatoryFields as exc:
            return Response(
                {
                    "detail": "This request cannot be submitted yet.",
                    "missing_fields": exc.fields,
                },
                status=http.HTTP_400_BAD_REQUEST,
            )
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        return Response(self.get_serializer(event).data)

    @action(detail=False, methods=["get"])
    def queue(self, request):
        """US-04.1 - the coordinator's queue of incoming requests."""
        if not request.user.is_coordinator:
            record_denied(
                request.user,
                action="GET /api/events/queue/",
                detail="queue is restricted to Event Coordinators",
            )
            raise PermissionDenied("Only an Event Coordinator can open the queue.")
        queryset = (
            EventRequest.objects.select_related("organisation", "coordinator")
            .exclude(status__in=QUEUE_EXCLUDED)
            .order_by("submitted_at")  # AC2 - oldest first
        )
        return Response(EventQueueSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def event_statuses(request):
    """US-06.1 AC2 and AC4 - the status vocabulary, filtered by who is asking."""
    internal = request.user.is_internal
    payload = [
        describe(value, for_internal_user=internal)
        for value in EventStatus.values
        if internal or value not in INTERNAL_STATUSES
    ]
    return Response(payload)
