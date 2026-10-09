from django.utils import timezone
from rest_framework import serializers

from apps.events.models import RoomLayout
from apps.venues.models import BookingStatus, Venue, VenueBlock, VenueBooking

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# SCRUM-9 AC3 - what a complete catalogue entry has, in the words staff use.
DESCRIBED_FIELDS = (
    ("location", "Location"),
    ("facilities", "Facilities"),
    ("layouts", "Supported room layouts"),
    ("accessibility", "Accessibility information"),
    ("operating_hours", "Operating hours"),
)


def _name(user):
    if user is None:
        return None
    return user.get_full_name() or user.email


def describe_hours(venue) -> str | None:
    if venue.opens_at is None or venue.closes_at is None:
        return None
    days = ", ".join(DAY_NAMES[d] for d in sorted(venue.operating_days))
    return f"{venue.opens_at:%H:%M}-{venue.closes_at:%H:%M} ({days or 'no days'})"


class VenueSerializer(serializers.ModelSerializer):
    layout_labels = serializers.SerializerMethodField()
    operating_hours = serializers.SerializerMethodField()
    operational_status = serializers.SerializerMethodField()
    missing_information = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = [
            "id",
            "name",
            "location",
            "capacity",
            "facilities",
            "layouts",
            "layout_labels",
            "wheelchair_access",
            "accessibility_notes",
            "opens_at",
            "closes_at",
            "operating_days",
            "operating_hours",
            "is_active",
            "operational_status",
            "missing_information",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        # SCRUM-65 AC3.
        extra_kwargs = {
            "capacity": {"error_messages": {"min_value": "Capacity must be at least one person."}}
        }

    def get_layout_labels(self, obj) -> list[str]:
        return [RoomLayout(value).label for value in obj.layouts if value in RoomLayout.values]

    def get_operating_hours(self, obj) -> str | None:
        return describe_hours(obj)

    def get_operational_status(self, obj) -> str:
        # SCRUM-9 AC4 / SCRUM-13 AC2.
        if not obj.is_active:
            return "Out of service"
        if obj.is_blocked_at():
            return "Blocked"
        return "In service"

    def get_missing_information(self, obj) -> list[str]:
        present = {
            "location": bool(obj.location),
            "facilities": bool(obj.facilities),
            "layouts": bool(obj.layouts),
            "accessibility": obj.wheelchair_access is not None or bool(obj.accessibility_notes),
            "operating_hours": describe_hours(obj) is not None,
        }
        return [label for key, label in DESCRIBED_FIELDS if not present[key]]

    def get_updated_by_name(self, obj) -> str | None:
        return _name(obj.updated_by)

    def validate_layouts(self, value):
        unknown = [v for v in value if v not in RoomLayout.values]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown layout: {', '.join(map(str, unknown))}. "
                f"Choose from {', '.join(RoomLayout.labels)}."
            )
        return sorted(set(value), key=RoomLayout.values.index)

    def validate_facilities(self, value):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("Facilities must be a list of names.")
        cleaned = []
        for item in value:
            item = item.strip()
            if item and item.casefold() not in {c.casefold() for c in cleaned}:
                cleaned.append(item)
        return cleaned

    def validate_operating_days(self, value):
        if not isinstance(value, list) or any(day not in range(7) for day in value):
            raise serializers.ValidationError("Operating days are numbers from 0 (Mon) to 6 (Sun).")
        return sorted(set(value))

    def validate(self, attrs):
        opens = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if opens and closes and closes <= opens:
            raise serializers.ValidationError({"closes_at": "Closing time must be after opening."})
        return attrs


class VenueBlockSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    venue_name = serializers.CharField(source="venue.name", read_only=True)

    class Meta:
        model = VenueBlock
        fields = [
            "id",
            "venue",
            "venue_name",
            "start",
            "end",
            "reason",
            "created_by_name",
            "created_at",
            "updated_by_name",
            "updated_at",
        ]
        read_only_fields = ["id", "venue", "created_at", "updated_at"]
        extra_kwargs = {
            "reason": {
                "error_messages": {
                    "blank": "Say why the venue is unavailable.",
                    "required": "Say why the venue is unavailable.",
                }
            }
        }

    def get_created_by_name(self, obj) -> str | None:
        return _name(obj.created_by)

    def get_updated_by_name(self, obj) -> str | None:
        return _name(obj.updated_by)

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "The block must end after it starts."})
        return attrs


class BookingRequestSerializer(serializers.ModelSerializer):
    """SCRUM-11 AC1-AC3 - what a coordinator states when requesting a venue."""

    class Meta:
        model = VenueBooking
        fields = [
            "event",
            "venue",
            "start",
            "end",
            "attendance",
            "layout",
            "facilities",
            "accessibility_needs",
            "notes",
        ]
        extra_kwargs = {
            "event": {"error_messages": {"required": "Choose the event this venue is for."}},
            "venue": {"error_messages": {"required": "Choose a venue."}},
            "start": {"error_messages": {"required": "Enter the date and start time."}},
            "end": {"error_messages": {"required": "Enter the date and end time."}},
            "attendance": {
                "error_messages": {
                    "required": "Enter the expected attendance.",
                    "min_value": "Attendance must be at least one person.",
                }
            },
        }

    validate_facilities = VenueSerializer.validate_facilities

    def validate_start(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("The booking must start in the future.")
        return value

    def validate(self, attrs):
        if attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError({"end": "The end must be after the start."})
        return attrs


class BookingSerializer(serializers.ModelSerializer):
    """SCRUM-72 AC1 / SCRUM-73 AC2 / SCRUM-67 AC4 / SCRUM-69 AC1 - a booking as displayed."""

    event_name = serializers.CharField(source="event.name", read_only=True)
    event_status = serializers.CharField(source="event.status", read_only=True)
    venue_name = serializers.CharField(source="venue.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    layout_label = serializers.CharField(source="get_layout_display", read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    withdrawn_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    suggested_venue_name = serializers.SerializerMethodField()
    conflicts = serializers.SerializerMethodField()

    class Meta:
        model = VenueBooking
        fields = [
            "id",
            "event",
            "event_name",
            "event_status",
            "venue",
            "venue_name",
            "start",
            "end",
            "attendance",
            "layout",
            "layout_label",
            "facilities",
            "accessibility_needs",
            "notes",
            "status",
            "status_display",
            "requested_by_name",
            "decided_by_name",
            "decided_at",
            "rejection_reason",
            "suggested_venue",
            "suggested_venue_name",
            "suggested_start",
            "suggested_end",
            "suggestion_note",
            "withdrawn_by_name",
            "withdrawn_at",
            "review_required",
            "review_reason",
            "review_start",
            "review_end",
            "reviewed_by_name",
            "reviewed_at",
            "review_outcome",
            "conflicts",
            "created_at",
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj):
        return _name(obj.decided_by)

    def get_withdrawn_by_name(self, obj):
        return _name(obj.withdrawn_by)

    def get_reviewed_by_name(self, obj):
        return _name(obj.reviewed_by)

    def get_suggested_venue_name(self, obj):
        return obj.suggested_venue.name if obj.suggested_venue else None

    def get_conflicts(self, obj) -> list[dict]:
        # Only an undecided request can conflict; a confirmed one is the holder.
        if obj.status != BookingStatus.PENDING:
            return []
        from apps.venues.bookings import conflict_row, conflicts_for

        return [conflict_row(c) for c in conflicts_for(obj)]


class RejectBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, required=False, default="")
    suggested_venue = serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(), required=False, allow_null=True
    )
    suggested_start = serializers.DateTimeField(required=False, allow_null=True)
    suggested_end = serializers.DateTimeField(required=False, allow_null=True)
    suggestion_note = serializers.CharField(required=False, allow_blank=True, default="")
    acknowledge_warning = serializers.BooleanField(required=False, default=False)


class ReviewInputSerializer(serializers.Serializer):
    """SCRUM-80 - staff record whether an affected arrangement can follow the change."""

    accommodated = serializers.BooleanField(
        error_messages={"required": "Say whether the change can be accommodated."}
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    start = serializers.DateTimeField(required=False, allow_null=True, default=None)
    end = serializers.DateTimeField(required=False, allow_null=True, default=None)
