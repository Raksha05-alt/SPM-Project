from rest_framework import serializers

from apps.venues.discovery import assess_venue
from apps.venues.layouts import cached_label_map
from apps.venues.models import LayoutType, Venue
from apps.venues.serializers import VenueSerializer


class VenueSearchCriteriaSerializer(serializers.Serializer):
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    attendance = serializers.IntegerField(required=False, min_value=1)
    layout = serializers.CharField(max_length=20, required=False, allow_blank=True)
    facilities = serializers.ListField(
        child=serializers.CharField(max_length=200), required=False, default=list, max_length=50
    )

    def validate_layout(self, value):
        # SCRUM-91 - search by any catalogue layout, including retired ones still on venues.
        if value and not LayoutType.objects.filter(code=value).exists():
            raise serializers.ValidationError("Unknown layout.")
        return value

    def validate(self, attrs):
        if ("start" in attrs) != ("end" in attrs):
            raise serializers.ValidationError(
                "Provide both event start and end, or leave both empty."
            )
        if "start" in attrs and attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError("Event end must be after its start.")
        facilities = []
        for item in attrs.get("facilities", []):
            if item.casefold() not in {saved.casefold() for saved in facilities}:
                facilities.append(item)
        attrs["facilities"] = facilities
        return attrs


class VenueMatchSerializer(serializers.Serializer):
    venue = VenueSerializer()
    criteria = serializers.ListField(child=serializers.DictField())
    matches_recorded_requirements = serializers.BooleanField()
    availability_status = serializers.CharField()


class AddShortlistSerializer(serializers.Serializer):
    venue_id = serializers.PrimaryKeyRelatedField(source="venue", queryset=Venue.objects.all())
    criteria = VenueSearchCriteriaSerializer(required=False, default=dict)


class VenueShortlistEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    search_criteria = serializers.JSONField()
    match = serializers.SerializerMethodField()

    def get_match(self, obj):
        criteria = dict(obj.search_criteria)
        # Clearing a search filter must not silently constrain that search.
        # A saved shortlist can still flag blocks against its event's period.
        if not criteria.get("start") and obj.event.preferred_start and obj.event.preferred_end:
            criteria.update(
                start=obj.event.preferred_start.isoformat(),
                end=obj.event.preferred_end.isoformat(),
            )
        labels = cached_label_map(self.context)
        match = assess_venue(obj.venue, criteria, labels)
        return VenueMatchSerializer(match, context=self.context).data
