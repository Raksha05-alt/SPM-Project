from django.db import transaction
from rest_framework import status as http
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import Role, User
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import (
    ATTENDEE_VISIBLE_STATUSES,
    COORDINATOR_NEXT_ACTIONS,
    INTERNAL_STATUSES,
    EventStatus,
    InvalidTransition,
    describe,
)
from apps.events.models import EventRequest
from apps.events.permissions import CanAccessEventRequest
from apps.events.serializers import (
    AssignedEventSerializer,
    AttendeeEventSerializer,
    ChangeLogSerializer,
    ClarificationInputSerializer,
    EventQueueSerializer,
    EventRequestSerializer,
    ReasonInputSerializer,
    ReassignInputSerializer,
    RejectionInputSerializer,
)
from apps.events.services import (
    EventClosed,
    EventNotFinished,
    InvalidReassignment,
    MissingClarificationDetails,
    MissingMandatoryFields,
    MissingRejectionReason,
    NotAssignedCoordinator,
    NotPermitted,
    approve_event,
    cancel_event,
    complete_event,
    log_changes,
    reassign_event,
    reject_event,
    request_clarification,
    snapshot,
    submit_event,
)

QUEUE_EXCLUDED = (EventStatus.DRAFT, EventStatus.REJECTED)


def filter_by_status(queryset, request):
    """SCRUM-57 - ``?status=PLANNING,APPROVED`` (or the parameter repeated).

    The filter only ever narrows a queryset that has already been limited to
    what the user may see, so it cannot reveal anything new (AC3).
    """
    values = [
        value.strip().upper()
        for raw in request.query_params.getlist("status")
        for value in raw.split(",")
        if value.strip()
    ]
    if not values:
        return queryset
    unknown = sorted(set(values) - set(EventStatus.values))
    if unknown:
        raise ValidationError({"status": [f"Unknown status: {', '.join(unknown)}."]})
    return queryset.filter(status__in=values)


class EventRequestViewSet(ModelViewSet):
    serializer_class = EventRequestSerializer
    # HasAnyRole is listed first on purpose. DRF stops at the first permission
    # class that returns False, and HasAnyRole is the class that writes the
    # audit row (US-01.2 AC4). With IsAuthenticated first, an anonymous request
    # would be refused before anything recorded the attempt.
    permission_classes = [HasAnyRole, IsAuthenticated, CanAccessEventRequest]
    allowed_roles = frozenset({Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.ATTENDEE})

    def get_serializer_class(self):
        if self.request.user.role == Role.ATTENDEE:
            return AttendeeEventSerializer
        return EventRequestSerializer

    def filter_queryset(self, queryset):
        if self.action == "list":
            queryset = filter_by_status(queryset, self.request)
        return super().filter_queryset(queryset)

    def get_queryset(self):
        user = self.request.user
        base = EventRequest.objects.select_related(
            "organisation", "created_by", "coordinator", "approved_by", "rejected_by", "updated_by"
        ).prefetch_related(
            "clarifications__requested_by",
            "assignment_history__coordinator",
            "assignment_history__previous_coordinator",
            "assignment_history__changed_by",
        )
        if user.role == Role.EVENT_ORGANISER:
            # US-02.3 / US-03.1 AC5 - a client sees only their own organisation.
            return base.filter(organisation_id=user.organisation_id)
        if user.role == Role.EVENT_COORDINATOR:
            # US-03.1 AC4 - drafts never reach ConnectSphere.
            return base.exclude(status=EventStatus.DRAFT)
        if user.role == Role.ATTENDEE:
            return base.filter(status__in=ATTENDEE_VISIBLE_STATUSES)
        return base.none()

    def get_object(self):
        """Look the object up across all rows so that a cross-organisation attempt
        is refused and audited (US-01.2 AC1) rather than silently returning 404."""
        obj = (
            EventRequest.objects.select_related(
                "organisation",
                "created_by",
                "coordinator",
                "approved_by",
                "rejected_by",
                "updated_by",
            )
            .prefetch_related(
                "clarifications__requested_by",
                "assignment_history__coordinator",
                "assignment_history__previous_coordinator",
                "assignment_history__changed_by",
            )
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

    def perform_update(self, serializer):
        """Serialize organiser saves with submissions and coordinator decisions."""
        denied = None
        with transaction.atomic():
            # Lock only the event row, without the nullable joins in get_object.
            locked = EventRequest.objects.select_for_update().get(pk=serializer.instance.pk)
            try:
                self.check_object_permissions(self.request, locked)
            except PermissionDenied as exc:
                # Commit the permission class's audit row before returning 403.
                denied = exc
            else:
                # Validate partial updates against current values, then save the
                # fresh instance so stale status/decision fields cannot return.
                current = self.get_serializer(
                    locked, data=serializer.initial_data, partial=serializer.partial
                )
                current.is_valid(raise_exception=True)
                before = snapshot(locked)
                serializer.instance = current.save(updated_by=self.request.user)
                if not locked.is_draft:
                    # SCRUM-60 - drafts are the client's private work in progress.
                    log_changes(serializer.instance, before, self.request.user)
        if denied is not None:
            raise denied

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

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Approve a submitted request so that venue and equipment planning can begin."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/approve/"
        try:
            if not request.user.is_coordinator:
                raise NotAssignedCoordinator
            approve_event(event, request.user)
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=action_name,
                obj=event,
                detail="only the assigned coordinator may approve",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can approve it."
            ) from None
        except InvalidTransition as exc:
            record_denied(request.user, action=action_name, obj=event, detail=str(exc))
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        except MissingMandatoryFields as exc:
            return Response(
                {
                    "detail": "This request does not have enough information to approve.",
                    "missing_fields": exc.fields,
                },
                status=http.HTTP_400_BAD_REQUEST,
            )
        event.refresh_from_db()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Reject a request ConnectSphere cannot support, with a recorded reason."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/reject/"
        payload = RejectionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            if not request.user.is_coordinator:
                raise NotAssignedCoordinator
            reject_event(event, request.user, payload.validated_data.get("reason", ""))
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=action_name,
                obj=event,
                detail="only the assigned coordinator may reject",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can reject it."
            ) from None
        except InvalidTransition as exc:
            record_denied(request.user, action=action_name, obj=event, detail=str(exc))
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        except MissingRejectionReason:
            return Response(
                {
                    "detail": "Enter a reason before rejecting this request.",
                    "reason": ["This field may not be blank."],
                },
                status=http.HTTP_400_BAD_REQUEST,
            )
        event.refresh_from_db()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"], url_path="request-clarification")
    def request_clarification(self, request, pk=None):
        """Ask the client for missing or unclear information."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/request-clarification/"
        payload = ClarificationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            if not request.user.is_coordinator:
                raise NotAssignedCoordinator
            request_clarification(
                event,
                request.user,
                payload.validated_data.get("message", ""),
                payload.validated_data["fields"],
            )
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=action_name,
                obj=event,
                detail="only the assigned coordinator may request clarification",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can request clarification."
            ) from None
        except InvalidTransition as exc:
            record_denied(request.user, action=action_name, obj=event, detail=str(exc))
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        except MissingClarificationDetails:
            return Response(
                {
                    "detail": "Say what information is needed before sending the request.",
                    "message": ["This field may not be blank."],
                },
                status=http.HTTP_400_BAD_REQUEST,
            )
        event.refresh_from_db()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """SCRUM-56 - cancel an event; a terminal event cannot be cancelled again."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/cancel/"
        payload = ReasonInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            cancel_event(event, request.user, payload.validated_data.get("reason", ""))
        except (NotAssignedCoordinator, NotPermitted):
            record_denied(
                request.user,
                action=action_name,
                obj=event,
                detail="only the client or the assigned coordinator may cancel",
            )
            raise PermissionDenied(
                "Only the client or the assigned coordinator can cancel this event."
            ) from None
        except InvalidTransition as exc:
            record_denied(request.user, action=action_name, obj=event, detail=str(exc))
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        event.refresh_from_db()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """SCRUM-56 - mark a confirmed event completed once it has taken place."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/complete/"
        try:
            if not request.user.is_coordinator:
                raise NotAssignedCoordinator
            complete_event(event, request.user)
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=action_name,
                obj=event,
                detail="only the assigned coordinator may complete",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can mark it completed."
            ) from None
        except InvalidTransition as exc:
            record_denied(request.user, action=action_name, obj=event, detail=str(exc))
            return Response({"detail": str(exc)}, status=http.HTTP_409_CONFLICT)
        except EventNotFinished:
            return Response(
                {"detail": "An event can only be marked completed after it has taken place."},
                status=http.HTTP_409_CONFLICT,
            )
        event.refresh_from_db()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """SCRUM-60 - field-level change history, internal staff only, newest first."""
        event = self.get_object()
        if not request.user.is_internal:
            record_denied(
                request.user,
                action=f"GET /api/events/{event.pk}/history/",
                obj=event,
                detail="change history is internal planning information",
            )
            raise PermissionDenied("Change history is restricted to ConnectSphere staff.")
        entries = event.change_log.select_related("changed_by")
        return Response(ChangeLogSerializer(entries, many=True).data)

    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        """SCRUM-53 - hand the event to another coordinator."""
        event = self.get_object()
        action_name = f"POST /api/events/{event.pk}/reassign/"
        if not request.user.is_coordinator:
            record_denied(
                request.user, action=action_name, obj=event, detail="only staff may reassign"
            )
            raise PermissionDenied("Only ConnectSphere coordinators can reassign an event.")
        payload = ReassignInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            reassign_event(event, request.user, payload.validated_data["coordinator"])
        except EventClosed:
            detail = f"A {event.get_status_display()} event cannot be reassigned."
            record_denied(request.user, action=action_name, obj=event, detail=detail)
            return Response({"detail": detail}, status=http.HTTP_409_CONFLICT)
        except InvalidReassignment as exc:
            return Response(
                {"detail": str(exc), "coordinator": [str(exc)]}, status=http.HTTP_400_BAD_REQUEST
            )
        event.refresh_from_db()
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
            EventRequest.objects.select_related("organisation", "coordinator", "approved_by")
            .exclude(status__in=QUEUE_EXCLUDED)
            .order_by("submitted_at")  # AC2 - oldest first
        )
        queryset = filter_by_status(queryset, request)
        return Response(EventQueueSerializer(queryset, many=True).data)

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """SCRUM-54 - the events assigned to the signed-in coordinator."""
        if not request.user.is_coordinator:
            record_denied(
                request.user,
                action="GET /api/events/mine/",
                detail="assigned events are restricted to Event Coordinators",
            )
            raise PermissionDenied("Only an Event Coordinator has assigned events.")
        events = (
            EventRequest.objects.select_related("organisation", "coordinator", "approved_by")
            .filter(coordinator=request.user)  # AC1 / AC4 - only this coordinator's
            .exclude(status=EventStatus.DRAFT)
            .order_by("submitted_at", "pk")
        )
        events = filter_by_status(events, request)
        # AC2 - events needing the coordinator's action first; the sort is
        # stable, so each group keeps oldest-submission-first order.
        ordered = sorted(events, key=lambda e: not COORDINATOR_NEXT_ACTIONS[e.status][1])
        return Response(AssignedEventSerializer(ordered, many=True).data)


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


@api_view(["GET"])
@permission_classes([HasAnyRole, IsAuthenticated])
def coordinators(request):
    """SCRUM-53 - the coordinators an event can be reassigned to (staff only)."""
    if not request.user.is_coordinator:
        record_denied(request.user, action="GET /api/coordinators/", detail="staff only")
        raise PermissionDenied("Only ConnectSphere coordinators can see this list.")
    rows = User.objects.filter(role=Role.EVENT_COORDINATOR, is_active=True).order_by(
        "first_name", "last_name", "email"
    )
    return Response(
        [
            {
                "id": user.pk,
                "name": user.get_full_name() or user.email,
                "email": user.email,
                "available": user.coordinator_available,
            }
            for user in rows
        ]
    )
