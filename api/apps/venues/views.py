from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.accounts.models import Role
from apps.core.audit import record, record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest, RoomLayout
from apps.venues.availability import OVERALL_LABELS, InvalidPeriod, overall, parse_period, segments
from apps.venues.bookings import (
    BookingRefused,
    NotAllowed,
    accept_suggestion,
    approve_booking,
    reject_booking,
    request_booking,
    withdraw_booking,
)
from apps.venues.matching import compare_venue, satisfies_all
from apps.venues.models import BookingStatus, Venue, VenueBlock, VenueBooking, VenueShortlist
from apps.venues.permissions import COORDINATOR_ONLY, INTERNAL_ROLES
from apps.venues.serializers import (
    BookingRequestSerializer,
    BookingSerializer,
    RejectBookingSerializer,
    VenueBlockSerializer,
    VenueSerializer,
)
from apps.venues.suitability import assess, requirements_of, unmet


def require_venue_staff(request, action: str, obj=None):
    if request.user.role != Role.VENUE_STAFF:
        record_denied(request.user, action=action, obj=obj, detail="venue staff only")
        raise PermissionDenied("Only Venue Staff can change venue records.")


def require_coordinator(request, action: str, obj=None):
    if not request.user.is_coordinator:
        record_denied(request.user, action=action, obj=obj, detail="event coordinators only")
        raise PermissionDenied("Only Event Coordinators can do this.")


def period_from(request):
    try:
        return parse_period(request.query_params.get("start"), request.query_params.get("end"))
    except InvalidPeriod as exc:
        raise ValidationError({"detail": str(exc)}) from None


def occupied_periods(venue, *, exclude_event_id=None):
    """Periods in which the venue cannot be offered: active blocks and confirmed bookings."""
    bookings = venue.bookings.filter(status=BookingStatus.APPROVED)
    if exclude_event_id:
        bookings = bookings.exclude(event_id=exclude_event_id)
    return [(b.start, b.end) for b in venue.active_blocks()] + [(b.start, b.end) for b in bookings]


def coordinator_event(request, event_id, action: str, *, write=False) -> EventRequest:
    """An event a coordinator may plan; writes are for the assigned coordinator only."""
    require_coordinator(request, action)
    event = get_object_or_404(EventRequest, pk=event_id)
    if event.status == EventStatus.DRAFT:
        record_denied(request.user, action=action, obj=event, detail="drafts are private")
        raise PermissionDenied("Drafts are not visible to ConnectSphere.")
    if write and event.coordinator_id != request.user.pk:
        record_denied(request.user, action=action, obj=event, detail="not the assigned coordinator")
        raise PermissionDenied("Only the coordinator assigned to this event can do this.")
    return event


class VenueViewSet(ModelViewSet):
    """SCRUM-65 maintain, SCRUM-9 view and SCRUM-5 layouts/facilities of venues."""

    serializer_class = VenueSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = INTERNAL_ROLES
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        return Venue.objects.select_related("updated_by").prefetch_related("blocks")

    def perform_create(self, serializer):
        require_venue_staff(self.request, "POST /api/venues/")
        venue = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        record(self.request.user, "POST /api/venues/", allowed=True, obj=venue)

    def update(self, request, *args, **kwargs):
        venue = self.get_object()
        action_name = f"{request.method} /api/venues/{venue.pk}/"
        require_venue_staff(request, action_name, venue)
        serializer = self.get_serializer(venue, data=request.data, partial=kwargs.get("partial"))
        serializer.is_valid(raise_exception=True)

        # SCRUM-5 AC4 - removing a layout that a confirmed booking relies on.
        removed = set(venue.layouts) - set(serializer.validated_data.get("layouts", venue.layouts))
        affected = list(
            venue.bookings.filter(
                status=BookingStatus.APPROVED, layout__in=removed, end__gt=timezone.now()
            ).select_related("event")
        )
        if affected and not request.data.get("confirm_layout_removal"):
            return Response(
                {
                    "detail": "Confirmed bookings use a layout you are removing.",
                    "affected_bookings": [
                        {
                            "id": booking.pk,
                            "event": booking.event_id,
                            "event_name": booking.event.name,
                            "layout": RoomLayout(booking.layout).label,
                            "start": booking.start,
                            "end": booking.end,
                        }
                        for booking in affected
                    ],
                },
                status=http.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            serializer.save(updated_by=request.user)
            for booking in affected:
                booking.review_required = True
                booking.review_reason = f"{venue.name} no longer supports the {RoomLayout(booking.layout).label} layout."
                booking.review_flagged_at = timezone.now()
                booking.save(
                    update_fields=["review_required", "review_reason", "review_flagged_at"]
                )
        record(request.user, action_name, allowed=True, obj=venue)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"])
    def blocks(self, request, pk=None):
        """SCRUM-13 - list a venue's blocks, or block it for a period."""
        venue = self.get_object()
        if request.method == "GET":
            rows = venue.active_blocks().select_related("created_by", "updated_by", "venue")
            return Response(VenueBlockSerializer(rows, many=True).data)
        action_name = f"POST /api/venues/{venue.pk}/blocks/"
        require_venue_staff(request, action_name, venue)
        serializer = VenueBlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        block = serializer.save(venue=venue, created_by=request.user, updated_by=request.user)
        record(request.user, action_name, allowed=True, obj=block)
        return Response(VenueBlockSerializer(block).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        """SCRUM-17 - one venue's availability over a period."""
        venue = self.get_object()
        start, end = period_from(request)
        pieces = segments(venue, start, end)
        return Response(
            {
                "venue": venue.pk,
                "venue_name": venue.name,
                "start": start,
                "end": end,
                "segments": pieces,
            }
        )

    @action(detail=False, methods=["get"], url_path="availability")
    def compare(self, request):
        """SCRUM-62 - every venue's availability for the same period, side by side."""
        start, end = period_from(request)
        rows = []
        for venue in self.get_queryset():
            pieces = segments(venue, start, end)
            summary = overall(pieces)
            rows.append(
                {
                    "venue": venue.pk,
                    "venue_name": venue.name,
                    "capacity": venue.capacity,
                    "overall": summary,
                    "overall_label": OVERALL_LABELS[summary],
                    "segments": pieces,
                }
            )
        none_available = not any(row["overall"] in ("AVAILABLE", "PARTIAL") for row in rows)
        return Response(
            {
                "start": start,
                "end": end,
                "venues": rows,
                "none_available": none_available,
                "message": "No venue is available at any time in this period."
                if none_available
                else "",
            }
        )

    @action(detail=False, methods=["get"])
    def search(self, request):
        """SCRUM-64 - venues that satisfy every requirement entered; empty filters are ignored."""
        params = request.query_params
        criteria = {}
        attendance = params.get("attendance")
        if attendance:
            if not attendance.isdigit() or int(attendance) <= 0:
                raise ValidationError({"attendance": ["Enter a whole number of people."]})
            criteria["attendance"] = int(attendance)
        layout = params.get("layout")
        if layout:
            if layout not in RoomLayout.values:
                raise ValidationError({"layout": [f"Unknown layout: {layout}."]})
            criteria["layout"] = layout
        facilities = [f.strip() for f in params.get("facilities", "").split(",") if f.strip()]
        if facilities:
            criteria["facilities"] = facilities
        if params.get("location", "").strip():
            criteria["location"] = params["location"].strip()
        if params.get("wheelchair_access", "").lower() in ("1", "true", "yes"):
            criteria["wheelchair_access"] = True
        if params.get("start") or params.get("end"):
            start, end = period_from(request)
            criteria["start"], criteria["end"] = start.isoformat(), end.isoformat()

        results = []
        for venue in self.get_queryset():
            checks = compare_venue(venue, criteria, occupied_periods(venue))
            if satisfies_all(checks):
                results.append({**VenueSerializer(venue).data, "checks": checks})
        return Response(
            {
                "results": results,
                "message": "" if results else "No venue matched every requirement you entered.",
            }
        )

    @action(detail=True, methods=["get"])
    def suitability(self, request, pk=None):
        """SCRUM-71 - is this venue suitable for this event, and if not, why?"""
        venue = self.get_object()
        event_id = request.query_params.get("event")
        if not event_id or not event_id.isdigit():
            raise ValidationError({"event": ["Choose an event."]})
        event = coordinator_event(
            request, int(event_id), f"GET /api/venues/{venue.pk}/suitability/"
        )
        checks = assess(venue, requirements_of(event))
        reasons = unmet(checks)
        return Response(
            {
                "venue": venue.pk,
                "venue_name": venue.name,
                "event": event.pk,
                "suitable": not reasons,
                "checks": checks,
                "warnings": reasons,
            }
        )


class VenueBlockViewSet(ModelViewSet):
    """SCRUM-13 AC6 - edit or remove a block, recording who and when."""

    serializer_class = VenueBlockSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = frozenset({Role.VENUE_STAFF})
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return VenueBlock.objects.filter(removed_at__isnull=True).select_related(
            "venue", "created_by", "updated_by"
        )

    def perform_update(self, serializer):
        block = serializer.save(updated_by=self.request.user)
        record(self.request.user, f"PATCH /api/venue-blocks/{block.pk}/", allowed=True, obj=block)

    def perform_destroy(self, instance):
        instance.removed_at = timezone.now()
        instance.removed_by = self.request.user
        instance.save(update_fields=["removed_at", "removed_by", "updated_at"])
        record(
            self.request.user,
            f"DELETE /api/venue-blocks/{instance.pk}/",
            allowed=True,
            obj=instance,
        )


def shortlist_row(entry: VenueShortlist) -> dict:
    """SCRUM-68 AC3 / AC4 - what the venue satisfies, and whether it is still available."""
    event, venue = entry.event, entry.venue
    checks = assess(venue, requirements_of(event))
    free = venue.is_active
    if event.preferred_start and event.preferred_end:
        free = free and not any(
            start < event.preferred_end and end > event.preferred_start
            for start, end in occupied_periods(venue, exclude_event_id=event.pk)
        )
    return {
        "venue": venue.pk,
        "venue_name": venue.name,
        "capacity": venue.capacity,
        "location": venue.location,
        "satisfied": [c["criterion"] for c in checks if c["matches"]],
        "not_satisfied": [
            {"criterion": c["criterion"], "reason": c["reason"]} for c in checks if not c["matches"]
        ],
        "no_longer_available": not free,
        "added_at": entry.added_at,
    }


class ShortlistView(APIView):
    """SCRUM-68 - the venues shortlisted for an event."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = COORDINATOR_ONLY

    def get(self, request, event_id):
        event = coordinator_event(request, event_id, f"GET /api/events/{event_id}/shortlist/")
        entries = event.venue_shortlist.select_related("venue", "event")
        return Response([shortlist_row(entry) for entry in entries])

    def post(self, request, event_id):
        action_name = f"POST /api/events/{event_id}/shortlist/"
        event = coordinator_event(request, event_id, action_name, write=True)
        venue_id = request.data.get("venue")
        venue = Venue.objects.filter(pk=venue_id).first() if str(venue_id).isdigit() else None
        if venue is None:
            raise ValidationError({"venue": ["Choose a venue from the search results."]})
        entry, _ = VenueShortlist.objects.get_or_create(
            event=event, venue=venue, defaults={"added_by": request.user}
        )
        return Response(shortlist_row(entry), status=http.HTTP_201_CREATED)


class ShortlistEntryView(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = COORDINATOR_ONLY

    def delete(self, request, event_id, venue_id):
        action_name = f"DELETE /api/events/{event_id}/shortlist/{venue_id}/"
        event = coordinator_event(request, event_id, action_name, write=True)
        get_object_or_404(VenueShortlist, event=event, venue_id=venue_id).delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


BOOKING_ROLES = frozenset({Role.EVENT_COORDINATOR, Role.VENUE_STAFF})


class VenueBookingViewSet(ReadOnlyModelViewSet):
    """SCRUM-11 request, SCRUM-72/73 decide, SCRUM-67 withdraw, SCRUM-69 conflicts."""

    serializer_class = BookingSerializer
    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = BOOKING_ROLES

    def get_queryset(self):
        bookings = VenueBooking.objects.select_related(
            "event",
            "venue",
            "requested_by",
            "decided_by",
            "withdrawn_by",
            "suggested_venue",
        ).exclude(event__status=EventStatus.DRAFT)
        params = self.request.query_params
        if params.get("status"):
            wanted = [value for value in params["status"].split(",") if value]
            unknown = [value for value in wanted if value not in BookingStatus.values]
            if unknown:
                raise ValidationError({"status": [f"Unknown status: {', '.join(unknown)}."]})
            bookings = bookings.filter(status__in=wanted)
        for field in ("event", "venue"):
            value = params.get(field)
            if value:
                if not value.isdigit():
                    raise ValidationError({field: ["Must be an id."]})
                bookings = bookings.filter(**{f"{field}_id": int(value)})
        return bookings

    def _run(self, request, action_name, booking, work, success=http.HTTP_200_OK):
        try:
            result = work()
        except NotAllowed:
            record_denied(
                request.user, action=action_name, obj=booking, detail="not the assigned coordinator"
            )
            raise PermissionDenied(
                "Only the coordinator assigned to this event can do this."
            ) from None
        except BookingRefused as exc:
            return Response({"detail": exc.detail, **exc.extra}, status=exc.status)
        record(request.user, action_name, allowed=True, obj=result)
        return Response(BookingSerializer(result).data, status=success)

    def create(self, request):
        action_name = "POST /api/venue-bookings/"
        require_coordinator(request, action_name)
        serializer = BookingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        event = coordinator_event(request, data.pop("event").pk, action_name, write=True)
        return self._run(
            request,
            action_name,
            event,
            lambda: request_booking(event, request.user, data),
            success=http.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        booking = self.get_object()
        action_name = f"POST /api/venue-bookings/{booking.pk}/approve/"
        require_venue_staff(request, action_name, booking)
        return self._run(
            request, action_name, booking, lambda: approve_booking(booking, request.user)
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        booking = self.get_object()
        action_name = f"POST /api/venue-bookings/{booking.pk}/reject/"
        require_venue_staff(request, action_name, booking)
        serializer = RejectBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        acknowledge = data.pop("acknowledge_warning")
        return self._run(
            request,
            action_name,
            booking,
            lambda: reject_booking(booking, request.user, reason, data, acknowledge),
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        booking = self.get_object()
        action_name = f"POST /api/venue-bookings/{booking.pk}/withdraw/"
        require_coordinator(request, action_name, booking)
        confirm = str(request.data.get("confirm", "")).lower() in ("true", "1")
        return self._run(
            request, action_name, booking, lambda: withdraw_booking(booking, request.user, confirm)
        )

    @action(detail=True, methods=["post"], url_path="accept-suggestion")
    def accept_suggestion(self, request, pk=None):
        booking = self.get_object()
        action_name = f"POST /api/venue-bookings/{booking.pk}/accept-suggestion/"
        require_coordinator(request, action_name, booking)

        def work():
            if booking.event.coordinator_id != request.user.pk:
                raise NotAllowed
            return accept_suggestion(booking, request.user)

        return self._run(request, action_name, booking, work, success=http.HTTP_201_CREATED)
