from rest_framework import serializers

from apps.equipment.models import (
    EquipmentRequest,
    EquipmentRequestChange,
    EquipmentReservation,
    EquipmentType,
)


def _name(user):
    if user is None:
        return None
    return user.get_full_name() or user.email


class EquipmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentType
        fields = [
            "id",
            "name",
            "category",
            "description",
            "total_quantity",
            "out_of_service_quantity",
            "out_of_service_reason",
            "expected_return",
        ]


class ReservationSerializer(serializers.ModelSerializer):
    reserved_by_name = serializers.SerializerMethodField()
    released_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentReservation
        fields = [
            "id",
            "quantity",
            "start",
            "end",
            "reserved_by_name",
            "reserved_at",
            "released_at",
            "released_by_name",
            "release_reason",
        ]

    def get_reserved_by_name(self, obj):
        return _name(obj.reserved_by)

    def get_released_by_name(self, obj):
        return _name(obj.released_by)


class ChangeSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentRequestChange
        fields = ["description", "changed_by_name", "changed_at"]

    def get_changed_by_name(self, obj):
        return _name(obj.changed_by)


class EquipmentRequestSerializer(serializers.ModelSerializer):
    """SCRUM-74 AC3 / SCRUM-75 AC4 - a request with its reservations and history."""

    event_name = serializers.CharField(source="event.name", read_only=True)
    equipment_name = serializers.CharField(source="equipment_type.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reserved_quantity = serializers.IntegerField(read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    withdrawn_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    reservations = ReservationSerializer(many=True, read_only=True)
    changes = ChangeSerializer(many=True, read_only=True)

    class Meta:
        model = EquipmentRequest
        fields = [
            "id",
            "event",
            "event_name",
            "equipment_type",
            "equipment_name",
            "quantity",
            "technical_requirements",
            "status",
            "status_display",
            "reserved_quantity",
            "requested_by_name",
            "created_at",
            "withdrawn_by_name",
            "withdrawn_at",
            "unavailable_reason",
            "review_required",
            "review_reason",
            "reviewed_by_name",
            "reviewed_at",
            "review_outcome",
            "reservations",
            "changes",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "withdrawn_at",
            "unavailable_reason",
            "review_required",
            "review_reason",
            "reviewed_at",
            "review_outcome",
        ]
        extra_kwargs = {
            "event": {"error_messages": {"required": "Choose the event this equipment is for."}},
            "equipment_type": {"error_messages": {"required": "Choose the equipment type."}},
            "quantity": {
                "error_messages": {
                    "required": "Enter the quantity required.",
                    "min_value": "The quantity must be at least 1.",
                    "invalid": "The quantity must be a whole number.",
                }
            },
        }

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_withdrawn_by_name(self, obj):
        return _name(obj.withdrawn_by)

    def get_reviewed_by_name(self, obj):
        return _name(obj.reviewed_by)

    def validate(self, attrs):
        if self.instance is not None and ("event" in attrs or "equipment_type" in attrs):
            raise serializers.ValidationError(
                "The event and equipment type cannot be changed; withdraw and request again."
            )
        return attrs


class EquipmentReviewInputSerializer(serializers.Serializer):
    accommodated = serializers.BooleanField(
        error_messages={"required": "Say whether the change can be accommodated."}
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
