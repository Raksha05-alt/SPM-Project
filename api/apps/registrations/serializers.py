from rest_framework import serializers

from apps.registrations.models import Registration
from apps.venues.models import BookingStatus


def confirmed_venues(event) -> list[dict]:
    """SCRUM-21 AC4 - where a confirmed event takes place."""
    if event.status not in ("CONFIRMED", "COMPLETED"):
        return []
    return [
        {"name": b.venue.name, "location": b.venue.location, "start": b.start, "end": b.end}
        for b in event.venue_bookings.filter(status=BookingStatus.APPROVED).select_related("venue")
    ]


class RegistrationInputSerializer(serializers.Serializer):
    """SCRUM-21 AC2 - the information an Attendee must give to register."""

    full_name = serializers.CharField(
        max_length=200,
        error_messages={"required": "Enter your full name.", "blank": "Enter your full name."},
    )
    email = serializers.EmailField(
        error_messages={
            "required": "Enter your email address.",
            "blank": "Enter your email address.",
            "invalid": "Enter a valid email address.",
        }
    )
    accessibility_needs = serializers.CharField(required=False, allow_blank=True, default="")


class RegistrationSerializer(serializers.ModelSerializer):
    """An Attendee's own registration with the event's confirmed details."""

    event_name = serializers.CharField(source="event.name", read_only=True)
    event_start = serializers.DateTimeField(source="event.preferred_start", read_only=True)
    event_end = serializers.DateTimeField(source="event.preferred_end", read_only=True)
    event_status = serializers.CharField(source="event.get_status_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    venues = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = [
            "id",
            "event",
            "event_name",
            "event_start",
            "event_end",
            "event_status",
            "venues",
            "full_name",
            "email",
            "accessibility_needs",
            "status",
            "status_display",
            "registered_at",
            "waitlisted_at",
            "place_offered_at",
            "withdrawn_at",
        ]

    def get_venues(self, obj) -> list[dict]:
        return confirmed_venues(obj.event)


class EventRegistrationSerializer(serializers.ModelSerializer):
    """SCRUM-14 AC5 - registrations as the client and coordinator see them."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Registration
        fields = [
            "id",
            "full_name",
            "email",
            "accessibility_needs",
            "status",
            "status_display",
            "registered_at",
            "waitlisted_at",
            "withdrawn_at",
        ]
