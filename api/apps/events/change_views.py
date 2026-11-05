"""SCRUM-20 - Request a change to an event (Sprint 4 gate INTAKE).

GET  /api/events/<event_id>/change-requests/   the event's change requests (AC5)
POST /api/events/<event_id>/change-requests/   the organiser requests a change (AC1)

SCRUM-59/78 - assess and decide a change request (Sprint 4 gate ASSESS):

GET  /api/change-requests/<id>/impact/   what the change would affect (read-only)
POST /api/change-requests/<id>/decide/   the assigned coordinator approves or rejects

Readers: the event's own organisation, its assigned coordinator and Leads.
Every refusal is audited.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.change_requests import (
    ChangeAlreadyDecided,
    ChangeDecisionError,
    ChangeRequestError,
    NotAssignedCoordinator,
    NotEventOrganiser,
    StaleChangeRequest,
    decide_change,
    request_change,
)
from apps.events.history_views import _display
from apps.events.impact import (
    ApplyRefused,
    NotArrangementStaff,
    apply_change,
    assess_change,
    change_history,
    keep_original,
    review_arrangement,
)
from apps.events.models import EventChangeRequest, EventRequest
from apps.venues.layouts import cached_label_map


def _name(user):
    return None if user is None else (user.get_full_name() or user.email)


class ChangeRequestSerializer(serializers.ModelSerializer):
    """AC5 - the request, its current status and any decision."""

    requested_by_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    proposed_changes = serializers.SerializerMethodField()

    class Meta:
        model = EventChangeRequest
        fields = [
            "id",
            "event",
            "description",
            "reason",
            "proposed_values",
            "proposed_changes",
            "target_bookings",
            "target_equipment_requests",
            "revision",
            "significant",
            "status",
            "status_label",
            "status_changed_at",
            "requested_by_name",
            "requested_at",
            "decided_by_name",
            "decided_at",
            "decision_reason",
            "applied_at",
            "completed_at",
            "completion_note",
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj):
        return _name(obj.decided_by)

    def get_proposed_changes(self, obj) -> list[dict]:
        """Each proposed field with its value at request time and the new value, readable."""
        labels = cached_label_map(self.context)
        rows = []
        for field, value in obj.proposed_values.items():
            label = str(EventRequest._meta.get_field(field).verbose_name).capitalize()
            rows.append(
                {
                    "field": field,
                    "label": label,
                    "current": _display(field, obj.source_values.get(field), labels),
                    "proposed": _display(field, value, labels),
                }
            )
        return rows


class ChangeRequestInputSerializer(serializers.Serializer):
    """Parses the request without coercion; the service names every problem."""

    description = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.JSONField(required=False, allow_null=True)
    proposed_values = serializers.JSONField(required=False, allow_null=True)
    target_bookings = serializers.JSONField(required=False, allow_null=True)
    target_equipment_requests = serializers.JSONField(required=False, allow_null=True)


class CanSeeChangeRequests(BasePermission):
    """The event's own organisation, its assigned coordinator, or a Lead."""

    message = "You do not have access to this event's change requests."

    def has_object_permission(self, request, view, event):
        user = request.user
        if user.role == Role.EVENT_ORGANISER:
            allowed = event.organisation_id == user.organisation_id
            reason = "event belongs to another client organisation"
        elif event.status == EventStatus.DRAFT:
            allowed, reason = False, "drafts are not visible to ConnectSphere"
        elif user.role == Role.EVENT_COORDINATOR:
            allowed = event.coordinator_id == user.pk
            reason = "coordinator is not assigned to this event"
        else:
            allowed, reason = True, ""
        if not allowed:
            record_denied(user, action=f"{request.method} {request.path}", obj=event, detail=reason)
        return allowed


class EventChangeRequestsView(APIView):
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, CanSeeChangeRequests]

    @property
    def allowed_roles(self):
        if self.request.method == "POST":
            return frozenset({Role.EVENT_ORGANISER})
        return frozenset(
            {Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD}
        )

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        changes = (
            EventChangeRequest.objects.filter(event=event)
            .select_related("requested_by", "decided_by")
            .order_by("-requested_at", "-pk")
        )
        return Response(ChangeRequestSerializer(changes, many=True).data)

    def post(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        payload = ChangeRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            change = request_change(
                event=event, requested_by=request.user, **payload.validated_data
            )
        except NotEventOrganiser:
            record_denied(
                request.user,
                action=f"POST /api/events/{event_id}/change-requests/",
                obj=event,
                detail="only the event's own organisation may request a change",
            )
            raise PermissionDenied("You can only request changes to your own events.") from None
        except ChangeRequestError as exc:
            return Response(
                {
                    "detail": "The change request could not be sent.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                # AC2 - the receipt: Pending, and who will review it.
                "detail": (
                    "Your change request has been sent and is Pending review."
                    if event.coordinator_id
                    else "Your change request has been sent to ConnectSphere and is Pending review."
                ),
                "change_request": ChangeRequestSerializer(change).data,
            },
            status=status.HTTP_201_CREATED,
        )


def _change_for(request, change_id):
    """The change request, after the event-level access check (and its audit)."""
    change = get_object_or_404(
        EventChangeRequest.objects.select_related("event", "requested_by", "decided_by"),
        pk=change_id,
    )
    if not CanSeeChangeRequests().has_object_permission(request, None, change.event):
        raise PermissionDenied(CanSeeChangeRequests.message)
    return change


class ChangeImpactView(APIView):
    """SCRUM-59 AC1 / SCRUM-78 AC1-AC4 - the read-only assessment of a change request."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD})

    def get(self, request, change_id):
        change = _change_for(request, change_id)
        return Response(assess_change(change))


class DecisionInputSerializer(serializers.Serializer):
    """Parses the decision without coercion; the service names every problem."""

    decision = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.JSONField(required=False, allow_null=True)


class ChangeDecisionView(APIView):
    """SCRUM-78 AC5 - the assigned coordinator approves or rejects, with a reason."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def post(self, request, change_id):
        change = _change_for(request, change_id)
        payload = DecisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            decided, assessment = decide_change(
                change=change, actor=request.user, **payload.validated_data
            )
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=f"POST /api/change-requests/{change_id}/decide/",
                obj=change.event,
                detail="only the assigned coordinator may decide a change request",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can decide its change requests."
            ) from None
        except ChangeDecisionError as exc:
            return Response(
                {
                    "detail": "The decision could not be recorded.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ChangeAlreadyDecided as exc:
            return Response(
                {
                    "detail": str(exc),
                    "change_request": ChangeRequestSerializer(exc.change).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except StaleChangeRequest:
            change.refresh_from_db()
            return Response(
                {
                    "detail": (
                        "The event has changed since this was requested, so it cannot be "
                        "approved as it stands. Review the current impact; you can reject it "
                        "and ask the organiser to send a new request."
                    ),
                    "assessment": assess_change(change),
                },
                status=status.HTTP_409_CONFLICT,
            )
        verb = "approved" if decided.status == "APPROVED" else "rejected"
        return Response(
            {
                "detail": f"Change request {verb}. The organiser has been notified.",
                "change_request": ChangeRequestSerializer(decided).data,
                "assessment": assessment,
            }
        )


# --------------------------------------------------------------------------
# SCRUM-80 - apply an approved change through staff review
#
# POST /api/change-requests/<id>/apply/          the coordinator starts applying it (AC1/AC6)
# POST /api/change-requests/<id>/keep-original/  ...or keeps the original after a refusal (AC3)
# GET  /api/change-requests/<id>/history/        request, decision and outcomes (AC5)
# GET  /api/arrangement-reviews/?status=PENDING  Venue Staff / Technical Support work (AC1)
# POST /api/arrangement-reviews/<id>/decide/     staff record their outcome (AC2/AC3)
# --------------------------------------------------------------------------

STAFF_KIND = {Role.VENUE_STAFF: "VENUE", Role.TECHNICAL_SUPPORT: "EQUIPMENT"}


def _refused(exc: ApplyRefused):
    return Response({"detail": exc.detail, **exc.extra}, status=exc.status)


class ApplyChangeView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def post(self, request, change_id):
        change = _change_for(request, change_id)
        try:
            applied, reviews = apply_change(change=change, actor=request.user)
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=f"POST /api/change-requests/{change_id}/apply/",
                obj=change.event,
                detail="only the assigned coordinator may apply a change",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can apply its changes."
            ) from None
        except StaleChangeRequest:
            change.refresh_from_db()
            return Response(
                {
                    "detail": (
                        "The event has changed since this was requested, so it cannot be "
                        "applied as it stands. Ask the organiser to send a new request."
                    ),
                    "assessment": assess_change(change),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ApplyRefused as exc:
            return _refused(exc)
        detail = (
            f"{len(reviews)} arrangement(s) sent to staff for review. The current "
            "arrangements stay in place until every review is recorded."
            if reviews
            else "The change affected no existing arrangement and has been applied."
        )
        return Response(
            {
                "detail": detail,
                "change_request": ChangeRequestSerializer(applied).data,
                "history": change_history(applied),
            }
        )


class KeepOriginalView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def post(self, request, change_id):
        change = _change_for(request, change_id)
        payload = DecisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            kept = keep_original(
                change=change, actor=request.user, reason=payload.validated_data.get("reason")
            )
        except NotAssignedCoordinator:
            record_denied(
                request.user,
                action=f"POST /api/change-requests/{change_id}/keep-original/",
                obj=change.event,
                detail="only the assigned coordinator may close a change",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can close its changes."
            ) from None
        except ChangeDecisionError as exc:
            return Response(
                {
                    "detail": "The outcome could not be recorded.",
                    **{k: [v] for k, v in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ApplyRefused as exc:
            return _refused(exc)
        return Response(
            {
                "detail": "The original arrangement is kept. The organiser has been notified.",
                "change_request": ChangeRequestSerializer(kept).data,
            }
        )


class ChangeHistoryView(APIView):
    """AC5 - the requested change, the decision, each arrangement outcome and who."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset(
        {
            Role.EVENT_ORGANISER,
            Role.EVENT_COORDINATOR,
            Role.EVENT_COORDINATOR_LEAD,
            Role.VENUE_STAFF,
            Role.TECHNICAL_SUPPORT,
        }
    )

    def get(self, request, change_id):
        return Response(change_history(_change_for(request, change_id)))


class ArrangementReviewInputSerializer(serializers.Serializer):
    outcome = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.JSONField(required=False, allow_null=True)


def _review_rows(reviews):
    rows = []
    for review in reviews:
        change = review.change_request
        rows.append(
            {
                "id": review.pk,
                "change_request": change.pk,
                "event": change.event_id,
                "event_name": change.event.name,
                "change_description": change.description,
                "change_status": change.status,
                "kind": review.kind,
                "name": (
                    review.booking.venue.name
                    if review.kind == "VENUE"
                    else review.equipment_request.equipment_type.name
                ),
                "quantity": review.equipment_request.quantity if review.equipment_request else None,
                "before": review.before,
                "proposed": review.proposed,
                "reasons": review.reasons,
                "outcome": review.outcome,
                "outcome_label": review.get_outcome_display(),
                "reviewed_by_name": _name(review.reviewed_by),
                "reviewed_at": review.reviewed_at,
                "review_reason": review.review_reason,
            }
        )
    return rows


def _reviews():
    from apps.events.models import ArrangementReview

    return ArrangementReview.objects.select_related(
        "change_request__event",
        "booking__venue",
        "equipment_request__equipment_type",
        "reviewed_by",
    )


class ArrangementReviewInboxView(APIView):
    """AC1 - each arrangement an approved change affects, for the staff who review it."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset(STAFF_KIND)

    def get(self, request):
        reviews = _reviews().filter(kind=STAFF_KIND[request.user.role])
        wanted = request.query_params.get("status", "PENDING")
        if wanted:
            from apps.events.models import ArrangementOutcome

            if wanted not in ArrangementOutcome.values:
                raise ValidationError({"status": ["Unknown review status."]})
            reviews = reviews.filter(outcome=wanted)
            if wanted == ArrangementOutcome.PENDING:
                # Only live work: a change still in review, on an event still going ahead.
                from apps.core.statuses import EventStatus
                from apps.events.models import ChangeRequestStatus

                reviews = reviews.filter(
                    change_request__status=ChangeRequestStatus.IN_REVIEW
                ).exclude(
                    change_request__event__status__in=(EventStatus.CANCELLED, EventStatus.COMPLETED)
                )
        return Response(_review_rows(reviews.order_by("-created_at", "-pk")))


class ArrangementReviewDecisionView(APIView):
    """AC2/AC3 - staff record whether they can accommodate the change."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset(STAFF_KIND)

    def post(self, request, review_id):
        review = get_object_or_404(_reviews(), pk=review_id)
        payload = ArrangementReviewInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            recorded, change = review_arrangement(
                review=review, actor=request.user, **payload.validated_data
            )
        except NotArrangementStaff:
            record_denied(
                request.user,
                action=f"POST /api/arrangement-reviews/{review_id}/decide/",
                obj=review.change_request.event,
                detail="this arrangement is reviewed by other staff",
            )
            raise PermissionDenied(
                "Venue Staff review venue bookings; Technical Support review equipment."
            ) from None
        except ChangeDecisionError as exc:
            return Response(
                {
                    "detail": "The outcome could not be recorded.",
                    **{k: [v] for k, v in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except StaleChangeRequest:
            return Response(
                {
                    "detail": "The event has changed since this change was approved; it cannot be applied."
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ApplyRefused as exc:
            return _refused(exc)
        recorded = _reviews().get(pk=recorded.pk)
        detail = (
            "The change has been applied: every arrangement was accommodated."
            if change.status == "APPLIED"
            else "Your outcome has been recorded."
        )
        return Response({"detail": detail, "review": _review_rows([recorded])[0]})
