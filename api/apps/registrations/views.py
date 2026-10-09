from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest
from apps.registrations.models import Registration, RegistrationStatus
from apps.registrations.serializers import (
    EventRegistrationSerializer,
    RegistrationInputSerializer,
    RegistrationSerializer,
)
from apps.registrations.services import (
    NotAllowed,
    RegistrationRefused,
    capacity_of,
    join_waitlist,
    places_left,
    register,
    withdraw,
)

ATTENDEE_ONLY = frozenset({Role.ATTENDEE})


def refused(exc: RegistrationRefused) -> Response:
    return Response({"detail": exc.detail, **exc.extra}, status=exc.status)


class EventRegistrationsView(APIView):
    """GET - the client and assigned coordinator see registrations (SCRUM-14 AC5, SCRUM-19 AC4).
    POST - an Attendee registers (SCRUM-21, SCRUM-81)."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.ATTENDEE})

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        user = request.user
        allowed = (
            user.role == Role.EVENT_ORGANISER and event.organisation_id == user.organisation_id
        ) or (user.role == Role.EVENT_COORDINATOR and event.coordinator_id == user.pk)
        if not allowed:
            record_denied(
                user,
                action=f"GET /api/events/{event_id}/registrations/",
                obj=event,
                detail="only the client and assigned coordinator see registrations",
            )
            raise PermissionDenied("Only the client and the assigned coordinator can see this.")
        registrations = event.registrations.all()
        return Response(
            {
                "capacity": capacity_of(event),
                "registered_count": registrations.filter(
                    status=RegistrationStatus.REGISTERED
                ).count(),
                "waitlist_count": registrations.filter(
                    status=RegistrationStatus.WAITLISTED
                ).count(),
                "places_left": places_left(event),
                "registrations": EventRegistrationSerializer(registrations, many=True).data,
            }
        )

    def post(self, request, event_id):
        return _attendee_action(request, event_id, register)


class WaitlistView(APIView):
    """SCRUM-19 - join the waiting list of a full event."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = ATTENDEE_ONLY

    def post(self, request, event_id):
        return _attendee_action(request, event_id, join_waitlist)


def _attendee_action(request, event_id, service):
    action_name = f"POST {request.path}"
    if request.user.role != Role.ATTENDEE:
        record_denied(request.user, action=action_name, detail="attendees only")
        raise PermissionDenied("Only Attendees can register for events.")
    event = get_object_or_404(EventRequest, pk=event_id)
    details = RegistrationInputSerializer(data=request.data)
    details.is_valid(raise_exception=True)
    try:
        registration = service(event, request.user, dict(details.validated_data))
    except RegistrationRefused as exc:
        return refused(exc)
    record(request.user, action_name, allowed=True, obj=registration)
    return Response(RegistrationSerializer(registration).data, status=http.HTTP_201_CREATED)


class RegistrationViewSet(ReadOnlyModelViewSet):
    """SCRUM-21 AC4 - my registrations; SCRUM-14 - withdraw from one."""

    serializer_class = RegistrationSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = ATTENDEE_ONLY

    def get_queryset(self):
        return Registration.objects.filter(attendee=self.request.user).select_related("event")

    def get_object(self):
        # Look across everyone's registrations so another Attendee is refused, not 404'd.
        return get_object_or_404(Registration.objects.select_related("event"), pk=self.kwargs["pk"])

    def retrieve(self, request, *args, **kwargs):
        registration = self.get_object()
        if registration.attendee_id != request.user.pk:
            raise PermissionDenied("This is not your registration.")
        return Response(self.get_serializer(registration).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        registration = self.get_object()
        action_name = f"POST /api/registrations/{registration.pk}/withdraw/"
        confirm = str(request.data.get("confirm", "")).lower() in ("true", "1")
        try:
            result = withdraw(registration, request.user, confirm)
        except NotAllowed:
            record_denied(
                request.user, action=action_name, obj=registration, detail="not the attendee"
            )
            raise PermissionDenied("Only the Attendee who registered can withdraw.") from None
        except RegistrationRefused as exc:
            return refused(exc)
        record(request.user, action_name, allowed=True, obj=result)
        return Response(self.get_serializer(result).data)
