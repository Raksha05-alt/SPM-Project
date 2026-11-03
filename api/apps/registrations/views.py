"""SCRUM-21/81 - registration API.

GET  /api/events/<id>/registration/          what an attendee sees about registering
POST /api/events/<id>/registration/          the attendee registers (21 AC1-AC3/AC5, 81 AC1-AC4)
GET  /api/registrations/mine/                the attendee's events and registration status (21 AC4)
GET  /api/events/<id>/registration-policy/   the policy and counts, for the organiser and staff
PUT  /api/events/<id>/registration-policy/   the organiser sets the policy (81)
GET  /api/events/<id>/registrations/         the event's registrations, for its managers

Every refusal is audited.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import ATTENDEE_VISIBLE_STATUSES, EventStatus
from apps.events.confirmation import confirmed_arrangements
from apps.events.models import EventRequest
from apps.registrations.models import Registration, RegistrationPolicy
from apps.registrations.services import (
    AlreadyRegistered,
    NotEventOrganiser,
    PolicyInvalid,
    RegistrationIncomplete,
    RegistrationRefused,
    active_registrations,
    capacity_of,
    register,
    registration_summary,
    set_policy,
)


class RegistrationSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="event.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Registration
        fields = [
            "id",
            "event",
            "event_name",
            "status",
            "status_label",
            "full_name",
            "email",
            "accessibility_requirements",
            "registered_at",
        ]
        read_only_fields = fields


def _event(pk):
    return get_object_or_404(
        EventRequest.objects.select_related("organisation", "coordinator", "created_by"), pk=pk
    )


def _deny(request, event, detail, message):
    record_denied(request.user, action=f"{request.method} {request.path}", obj=event, detail=detail)
    raise PermissionDenied(message)


def _public_event(event) -> dict:
    """The confirmed date, time and venue(s) an attendee may see (SCRUM-21 AC4)."""
    arrangements = confirmed_arrangements(event)
    return {
        "id": event.pk,
        "name": event.name,
        "status": event.status,
        "status_label": event.get_status_display(),
        "starts_at": event.preferred_start,
        "ends_at": event.preferred_end,
        "venues": [
            {
                "venue": v["venue"],
                "location": v["location"],
                "starts_at": v["starts_at"],
                "ends_at": v["ends_at"],
            }
            for v in arrangements["venues"]
        ],
    }


class RegisterView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.ATTENDEE})

    def _visible_event(self, request, event_id):
        event = _event(event_id)
        if event.status not in ATTENDEE_VISIBLE_STATUSES:
            # SCRUM-21 AC5 - an unconfirmed event is not offered to attendees at all.
            _deny(
                request, event, "event is not confirmed", "This event is not open for registration."
            )
        return event

    def get(self, request, event_id):
        event = self._visible_event(request, event_id)
        return Response(registration_summary(event, request.user))

    def post(self, request, event_id):
        event = self._visible_event(request, event_id)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            registration = register(
                event=event,
                attendee=request.user,
                full_name=data.get("full_name", ""),
                email=data.get("email", ""),
                accessibility_requirements=data.get("accessibility_requirements", ""),
            )
        except AlreadyRegistered as exc:
            # AC3 - refused, with the existing registration shown.
            return Response(
                {
                    "detail": "You are already registered for this event.",
                    "registration": RegistrationSerializer(exc.registration).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except RegistrationIncomplete as exc:
            return Response(
                {
                    "detail": "Some registration information is missing.",
                    "missing": list(exc.errors),
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RegistrationRefused as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code, **exc.extra},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "detail": f'You are registered for "{event.name}".',
                "registration": RegistrationSerializer(registration).data,
                "event": _public_event(event),
            },
            status=status.HTTP_201_CREATED,
        )


class MyRegistrationsView(APIView):
    """SCRUM-21 AC4 - the attendee's registered events with their confirmed details."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.ATTENDEE})

    def get(self, request):
        rows = (
            Registration.objects.filter(attendee=request.user)
            .select_related("event")
            .order_by("event__preferred_start", "pk")
        )
        return Response(
            [
                {**RegistrationSerializer(row).data, "event_details": _public_event(row.event)}
                for row in rows
            ]
        )


class PolicyInputSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    opens_at = serializers.DateTimeField(required=False, allow_null=True)
    closes_at = serializers.DateTimeField(required=False, allow_null=True)
    manually_closed = serializers.BooleanField(required=False)
    capacity = serializers.IntegerField(required=False, allow_null=True)


def _can_manage(user, event) -> bool:
    """The event's organisation, its assigned coordinator, or a Lead."""
    if user.role == Role.EVENT_ORGANISER:
        return user.organisation_id == event.organisation_id
    if user.role == Role.EVENT_COORDINATOR:
        return event.coordinator_id == user.pk
    return user.role == Role.EVENT_COORDINATOR_LEAD


def _policy_data(event) -> dict:
    policy = RegistrationPolicy.objects.filter(event=event).first()
    count = capacity_of(event, policy)
    return {
        "event": event.pk,
        "enabled": bool(policy and policy.enabled),
        "opens_at": policy.opens_at if policy else None,
        "closes_at": policy.closes_at if policy else None,
        "manually_closed": bool(policy and policy.manually_closed),
        "capacity": count.capacity,
        "registered": count.registered,
        "remaining": count.remaining,
        "full": count.full,
        "open": registration_summary(event)["open"],
    }


MANAGERS = frozenset({Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD})


class RegistrationPolicyView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = MANAGERS

    def get(self, request, event_id):
        event = _event(event_id)
        if event.status == EventStatus.DRAFT or not _can_manage(request.user, event):
            _deny(
                request, event, "not this event's manager", "You do not have access to this event."
            )
        return Response(_policy_data(event))

    def put(self, request, event_id):
        event = _event(event_id)
        payload = PolicyInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            set_policy(event=event, actor=request.user, **payload.validated_data)
        except NotEventOrganiser:
            _deny(
                request,
                event,
                "only the event's organiser sets registration",
                "Only the event's organiser can change its registration settings.",
            )
        except PolicyInvalid as exc:
            raise ValidationError(
                {field: [message] for field, message in exc.errors.items()}
            ) from None
        return Response(_policy_data(event))


class EventRegistrationsView(APIView):
    """Who is registered: the event's organiser, assigned coordinator and Leads only."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = MANAGERS

    def get(self, request, event_id):
        event = _event(event_id)
        if event.status == EventStatus.DRAFT or not _can_manage(request.user, event):
            _deny(
                request, event, "not this event's manager", "You do not have access to this event."
            )
        rows = Registration.objects.filter(event=event).order_by("registered_at", "pk")
        return Response(
            {
                "registered": active_registrations(event).count(),
                "registrations": RegistrationSerializer(rows, many=True).data,
            }
        )
