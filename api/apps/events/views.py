from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.events.permissions import CanAccessEventRequest
from apps.events.serializers import EventRequestSerializer


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
