from rest_framework import serializers

from apps.events.models import RoomLayout
from apps.venues.models import Venue

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
    created_by_name = serializers.SerializerMethodField()
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
            "in_service",
            "created_by_name",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        # AC3 - say why a zero or negative capacity is refused.
        extra_kwargs = {
            "capacity": {
                "error_messages": {
                    "min_value": "Capacity must be at least one person.",
                    "required": "Enter the venue's maximum capacity.",
                    "null": "Enter the venue's maximum capacity.",
                }
            },
        }

    def get_layout_labels(self, obj) -> list[str]:
        return [RoomLayout(value).label for value in obj.layouts if value in RoomLayout.values]

    def get_operating_hours(self, obj) -> str | None:
        return describe_hours(obj)

    def get_created_by_name(self, obj) -> str | None:
        return _name(obj.created_by)

    def get_updated_by_name(self, obj) -> str | None:
        return _name(obj.updated_by)

    def validate_layouts(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Layouts must be a list.")
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
        if not isinstance(value, list) or any(
            not isinstance(day, int) or day not in range(7) for day in value
        ):
            raise serializers.ValidationError("Operating days are numbers from 0 (Mon) to 6 (Sun).")
        return sorted(set(value))

    def validate(self, attrs):
        opens = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if opens and closes and closes <= opens:
            raise serializers.ValidationError({"closes_at": "Closing time must be after opening."})
        return attrs
