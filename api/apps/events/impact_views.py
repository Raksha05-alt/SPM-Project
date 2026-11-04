"""SCRUM-66 AC3 - why an approved venue was flagged for review."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.events.models import EventRequest, VenueReview
from apps.venues.models import BookingStatus

REVIEW_READERS = frozenset({Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD, Role.VENUE_STAFF})


class VenueReviewSerializer(serializers.ModelSerializer):
    venue = serializers.CharField(source="booking.venue.name")
    booking_status = serializers.CharField(source="booking.status")
    raised_by_name = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()

    class Meta:
        model = VenueReview
        fields = [
            "id",
            "booking",
            "venue",
            "booking_status",
            "reasons",
            "changed_fields",
            "source",
            "raised_by_name",
            "raised_at",
            "is_open",
            "resolved_at",
            "resolution",
        ]
        read_only_fields = fields

    def get_raised_by_name(self, review):
        user = review.raised_by
        return None if user is None else (user.get_full_name() or user.email)

    def get_is_open(self, review) -> bool:
        return review.resolved_at is None and review.booking.status == BookingStatus.APPROVED


class EventVenueReviewsView(APIView):
    """GET /api/events/<id>/venue-reviews/ - open reviews first, then the rest."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = REVIEW_READERS

    def get(self, request, event_id):
        event = get_object_or_404(EventRequest, pk=event_id)
        user = request.user
        if user.is_coordinator and event.coordinator_id != user.pk:
            record_denied(
                user,
                action=f"GET {request.path}",
                obj=event,
                detail="event is not assigned to this coordinator",
            )
            raise PermissionDenied("Only the coordinator assigned to this event can do this.")
        reviews = list(
            event.venue_reviews.select_related("booking__venue", "raised_by").order_by(
                "-raised_at", "-pk"
            )
        )
        data = VenueReviewSerializer(reviews, many=True).data
        return Response(
            {
                "event": event.pk,
                "open": [r for r in data if r["is_open"]],
                "history": [r for r in data if not r["is_open"]],
            }
        )
