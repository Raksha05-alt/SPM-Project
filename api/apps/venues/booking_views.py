"""SCRUM-11 - Request a venue booking (Sprint 3 gate G09).

GET  /api/events/<event_id>/venue-bookings/   the event's venue requests (AC5)
POST /api/events/<event_id>/venue-bookings/   the assigned coordinator requests a venue
GET  /api/venue-bookings/?status=PENDING      Venue Staff's booking-request inbox (AC4)

SCRUM-72 - Respond to a venue booking request (Sprint 3 gate G10):

GET  /api/venue-bookings/<id>/                one request's event, timing and requirements
POST /api/venue-bookings/<id>/approve/        Venue Staff approve a Pending request
POST /api/venue-bookings/<id>/reject/         Venue Staff reject one, with a reason

Venue booking requests are internal planning information: clients and
Attendees never reach them (SCRUM-1 AC2). Every refusal is audited.
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
from apps.events.models import EventRequest
from apps.venues.bookings import (
    BookingValidationError,
    InvalidBookingTransition,
    NotAssignedToEvent,
    VenueNotAvailable,
    approve_booking,
    reject_booking,
    request_booking,
    withdraw_booking,
)
from apps.venues.layouts import cached_label_map
from apps.venues.models import BookingStatus, Venue, VenueBooking
from apps.venues.suitability import VenueUnsuitable


def _name(user):
    return None if user is None else (user.get_full_name() or user.email)


class VenueBookingSerializer(serializers.ModelSerializer):
    buffer_review = serializers.SerializerMethodField()

    def get_buffer_review(self, obj):
        from apps.venues.occupancy import booking_review

        return booking_review(obj)

    event_name = serializers.CharField(source="event.name", read_only=True)
    organisation_name = serializers.CharField(source="event.organisation.name", read_only=True)
    venue_name = serializers.CharField(source="venue.name", read_only=True)
    layout_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    withdrawn_by_name = serializers.SerializerMethodField()
    withdrawn_at = serializers.SerializerMethodField()

    class Meta:
        model = VenueBooking
        fields = [
            "buffer_review",
            "id",
            "event",
            "event_name",
            "organisation_name",
            "venue",
            "venue_name",
            "starts_at",
            "ends_at",
            "attendance",
            "layout",
            "layout_name",
            "required_facilities",
            "wheelchair_access_required",
            "accessibility_notes",
            "status",
            "status_label",
            "status_changed_at",
            "requested_by_name",
            "requested_at",
            "decided_by_name",
            "decided_at",
            "decision_reason",
            "withdrawn_by_name",
            "withdrawn_at",
        ]
        read_only_fields = fields

    def get_layout_name(self, obj) -> str:
        return cached_label_map(self.context).get(obj.layout, obj.layout) if obj.layout else ""

    def get_requested_by_name(self, obj) -> str | None:
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj) -> str | None:
        return _name(obj.decided_by)

    def _withdrawal(self, obj):
        return obj.history.filter(to_status=BookingStatus.WITHDRAWN).select_related("actor").first()

    def get_withdrawn_by_name(self, obj):
        change = self._withdrawal(obj)
        return _name(change.actor) if change else None

    def get_withdrawn_at(self, obj):
        change = self._withdrawal(obj)
        return serializers.DateTimeField().to_representation(change.changed_at) if change else None


class BookingRequestInputSerializer(serializers.Serializer):
    """Parses the request; the booking service names every missing item (AC3)."""

    venue = serializers.IntegerField(required=False, allow_null=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    attendance = serializers.IntegerField(required=False, allow_null=True)
    layout = serializers.CharField(required=False, allow_blank=True, default="")
    required_facilities = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list
    )
    wheelchair_access_required = serializers.BooleanField(required=False, default=False)
    accessibility_notes = serializers.CharField(required=False, allow_blank=True, default="")


def _bookings():
    return VenueBooking.objects.select_related(
        "event__organisation", "venue", "requested_by", "decided_by"
    )


class CanSeeEventBookings(BasePermission):
    """Assigned coordinator, any Lead, or Venue Staff; drafts are never visible."""

    message = "You do not have access to this event's venue requests."

    def has_object_permission(self, request, view, event):
        user = request.user
        if event.status == EventStatus.DRAFT:
            allowed, reason = False, "drafts are not visible to ConnectSphere"
        elif user.role == Role.EVENT_COORDINATOR:
            allowed = event.coordinator_id == user.pk
            reason = "coordinator is not assigned to this event"
        else:
            allowed, reason = True, ""
        if not allowed:
            record_denied(user, action=f"{request.method} {request.path}", obj=event, detail=reason)
        return allowed


class EventVenueBookingsView(APIView):
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated, CanSeeEventBookings]

    @property
    def allowed_roles(self):
        if self.request.method == "POST":
            # AC6 - only coordinators request venues; the service checks assignment.
            return frozenset({Role.EVENT_COORDINATOR})
        return frozenset({Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD, Role.VENUE_STAFF})

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        bookings = _bookings().filter(event=event).order_by("-requested_at", "-pk")
        return Response(VenueBookingSerializer(bookings, many=True).data)

    def post(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        action = f"POST /api/events/{event_id}/venue-bookings/"
        payload = BookingRequestInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = dict(payload.validated_data)
        venue_id = values.pop("venue", None)
        venue = Venue.objects.filter(pk=venue_id).first() if venue_id is not None else None
        if venue_id is not None and venue is None:
            raise ValidationError({"venue": ["That venue does not exist."]})
        try:
            booking = request_booking(event=event, venue=venue, requested_by=request.user, **values)
        except NotAssignedToEvent:
            record_denied(
                request.user,
                action=action,
                obj=event,
                detail="only the assigned coordinator may request a venue",
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can request a venue."
            ) from None
        except BookingValidationError as exc:
            return Response(
                {
                    "detail": "The venue request is missing information or has invalid values.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except VenueUnsuitable as exc:
            return Response(
                {
                    "detail": f"{exc.result.venue_name} does not meet this event's requirements.",
                    "unmet_requirements": [reason.as_dict() for reason in exc.reasons],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except VenueNotAvailable as exc:
            return Response(
                {"detail": "The venue is not available for that period.", "reasons": exc.reasons},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                # AC4 - confirmation that the request reached Venue Staff.
                "detail": f"Your request for {booking.venue.name} has been sent to Venue Staff.",
                "booking": VenueBookingSerializer(_bookings().get(pk=booking.pk)).data,
            },
            status=status.HTTP_201_CREATED,
        )


class VenueBookingInboxView(APIView):
    """AC4 - Venue Staff see the booking requests waiting for them (decisions: VenueBookingDecisionView)."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.VENUE_STAFF})

    def get(self, request):
        bookings = _bookings().order_by("requested_at", "pk")
        wanted = request.query_params.get("status")
        if wanted:
            if wanted not in BookingStatus.values:
                raise ValidationError(
                    {"status": [f"Choose from {', '.join(BookingStatus.values)}."]}
                )
            bookings = bookings.filter(status=wanted)
        return Response(VenueBookingSerializer(bookings, many=True).data)


class WithdrawalInputSerializer(serializers.Serializer):
    expected_status = serializers.ChoiceField(choices=BookingStatus.choices)
    confirm_release = serializers.BooleanField(default=False)


class WithdrawVenueBookingView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated, CanSeeEventBookings]
    allowed_roles = frozenset({Role.EVENT_COORDINATOR})

    def post(self, request, event_id, booking_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        self.check_object_permissions(request, event)
        booking = get_object_or_404(_bookings(), pk=booking_id, event=event)
        payload = WithdrawalInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            booking = withdraw_booking(
                booking=booking, actor=request.user, **payload.validated_data
            )
        except NotAssignedToEvent:
            record_denied(
                request.user,
                action=f"POST {request.path}",
                obj=event,
                detail="only the current assigned coordinator may withdraw",
            )
            raise PermissionDenied("Only the current assigned coordinator may withdraw.") from None
        except BookingValidationError as exc:
            return Response({"detail": "Withdrawal refused.", **exc.errors}, status=409)
        except InvalidBookingTransition as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(
            {
                "detail": "Booking withdrawn. Venue Staff have been notified.",
                "booking": VenueBookingSerializer(booking).data,
            }
        )


class VenueBookingDetailView(APIView):
    """SCRUM-72 AC1 - the event, requested period and stated requirements of one request."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.VENUE_STAFF})

    def get(self, request, booking_id):
        booking = get_object_or_404(_bookings(), pk=booking_id)
        return Response(VenueBookingSerializer(booking).data)


class DecisionInputSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class VenueBookingDecisionView(APIView):
    """SCRUM-72 AC2-AC6 - Venue Staff approve or reject a Pending request.

    The deciding user and time come from the session and the server clock,
    never from the payload (AC6).
    """

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.VENUE_STAFF})
    decision = ""  # "approve" or "reject", set in urls.py

    def post(self, request, booking_id):
        booking = get_object_or_404(VenueBooking, pk=booking_id)
        payload = DecisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            if self.decision == "approve":
                decided = approve_booking(booking, request.user)
            else:
                decided = reject_booking(booking, request.user, payload.validated_data["reason"])
        except InvalidBookingTransition as exc:
            # AC5 - a decided request cannot be decided again.
            return Response(
                {"detail": f"This request has already been decided: {exc}", "status": exc.current},
                status=status.HTTP_409_CONFLICT,
            )
        except BookingValidationError as exc:
            # AC4 - a rejection without a reason; or the venue clashes or the event is closed.
            code = (
                status.HTTP_409_CONFLICT
                if "venue" in exc.errors or "event" in exc.errors
                else status.HTTP_400_BAD_REQUEST
            )
            return Response(
                {
                    "detail": "The decision could not be recorded.",
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=code,
            )
        except VenueUnsuitable as exc:
            return Response(
                {
                    "detail": f"{exc.result.venue_name} no longer meets this event's requirements.",
                    "unmet_requirements": [reason.as_dict() for reason in exc.reasons],
                },
                status=status.HTTP_409_CONFLICT,
            )
        except VenueNotAvailable as exc:
            return Response(
                {"detail": "The venue is not available for that period.", "reasons": exc.reasons},
                status=status.HTTP_409_CONFLICT,
            )
        verb = "approved" if decided.status == BookingStatus.APPROVED else "rejected"
        return Response(
            {
                "detail": f"Booking request {verb}. The Event Coordinator has been notified.",
                "booking": VenueBookingSerializer(_bookings().get(pk=decided.pk)).data,
            }
        )
