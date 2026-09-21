from django.utils import timezone
from rest_framework import serializers

from apps.core.statuses import STATUS_DESCRIPTIONS, EventStatus
from apps.events.models import EventRequest


class EventRequestSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    coordinator_name = serializers.SerializerMethodField()
    missing_mandatory_fields = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()

    class Meta:
        model = EventRequest
        fields = [
            "id",
            "name",
            "purpose",
            "description",
            "preferred_start",
            "preferred_end",
            "expected_attendance",
            "required_layout",
            "accessibility_needs",
            "equipment_notes",
            "registration_required",
            "status",
            "status_label",
            "status_description",
            "status_changed_at",
            "submitted_at",
            "organisation",
            "organisation_name",
            "created_by",
            "created_by_name",
            "coordinator",
            "coordinator_name",
            "missing_mandatory_fields",
            "is_editable",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_changed_at",
            "submitted_at",
            "organisation",
            "created_by",
            "coordinator",
            "created_at",
            "updated_at",
        ]

    def get_status_description(self, obj) -> str:
        return STATUS_DESCRIPTIONS[EventStatus(obj.status)]

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_coordinator_name(self, obj) -> str | None:
        if obj.coordinator is None:
            return None
        return obj.coordinator.get_full_name() or obj.coordinator.email

    def get_missing_mandatory_fields(self, obj) -> list[str]:
        return obj.missing_mandatory_fields()

    def get_is_editable(self, obj) -> bool:
        return obj.is_draft

    # --- field level rules. Only values actually supplied are checked, so that
    # --- an incomplete draft still saves (US-03.1 AC2).
    def validate_expected_attendance(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Expected attendance must be at least one person.")
        return value

    def validate_preferred_start(self, value):
        if value is not None and value < timezone.now():
            raise serializers.ValidationError("The preferred start date cannot be in the past.")
        return value

    def validate(self, attrs):
        start = attrs.get("preferred_start", getattr(self.instance, "preferred_start", None))
        end = attrs.get("preferred_end", getattr(self.instance, "preferred_end", None))
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"preferred_end": "The event must end after it starts."}
            )
        return attrs


class AttendeeEventSerializer(serializers.ModelSerializer):
    """Public event details that are safe and useful to an Attendee."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()

    class Meta:
        model = EventRequest
        fields = [
            "id",
            "name",
            "description",
            "preferred_start",
            "preferred_end",
            "accessibility_needs",
            "registration_required",
            "status",
            "status_label",
            "status_description",
            "status_changed_at",
        ]

    def get_status_description(self, obj) -> str:
        return STATUS_DESCRIPTIONS[EventStatus(obj.status)]


class EventQueueSerializer(serializers.ModelSerializer):
    """The narrower shape the coordinator queue needs (US-04.1 AC1)."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    coordinator_name = serializers.SerializerMethodField()

    class Meta:
        model = EventRequest
        fields = [
            "id",
            "name",
            "organisation_name",
            "preferred_start",
            "expected_attendance",
            "status",
            "status_label",
            "status_description",
            "submitted_at",
            "coordinator_name",
        ]

    def get_status_description(self, obj) -> str:
        return STATUS_DESCRIPTIONS[EventStatus(obj.status)]

    def get_coordinator_name(self, obj) -> str | None:
        if obj.coordinator is None:
            return None
        return obj.coordinator.get_full_name() or obj.coordinator.email
