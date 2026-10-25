from rest_framework import serializers

from apps.venues.models import VenueBlock, VenueBlockHistory


class PeriodSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "End must be after start."})
        return attrs


class VenueBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = VenueBlock
        fields = ["id", "reason", "starts_at", "ends_at", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        start = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        end = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"ends_at": "End must be after start."})
        return attrs


class VenueBlockHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = VenueBlockHistory
        fields = [
            "id",
            "block_id",
            "action",
            "reason",
            "starts_at",
            "ends_at",
            "actor",
            "actor_name",
            "created_at",
        ]

    def get_actor_name(self, obj):
        return (obj.actor.get_full_name() or obj.actor.email) if obj.actor else "Deleted user"
