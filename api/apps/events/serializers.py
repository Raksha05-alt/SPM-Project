from django.utils import timezone
from rest_framework import serializers

from apps.core.statuses import COORDINATOR_NEXT_ACTIONS, STATUS_DESCRIPTIONS, EventStatus
from apps.events.models import (
    ClarificationRequest,
    CoordinatorAssignment,
    EventChangeLog,
    EventRequest,
)
from apps.registrations import services as registrations
from apps.registrations.serializers import confirmed_venues


class ClarificationSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ClarificationRequest
        fields = ["id", "message", "fields", "requested_by_name", "requested_at", "resolved_at"]
        read_only_fields = fields

    def get_requested_by_name(self, obj) -> str | None:
        return _display_name(obj.requested_by)


class ClarificationInputSerializer(serializers.Serializer):
    message = serializers.CharField(allow_blank=True, trim_whitespace=True, required=False)
    fields = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
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
            ]
        ),
        required=False,
        default=list,
    )


class RejectionInputSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, trim_whitespace=True, required=False)


class ReassignInputSerializer(serializers.Serializer):
    coordinator = serializers.IntegerField()


class AssignmentHistorySerializer(serializers.ModelSerializer):
    previous_coordinator_name = serializers.SerializerMethodField()
    coordinator_name = serializers.SerializerMethodField()
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CoordinatorAssignment
        fields = [
            "id",
            "previous_coordinator",
            "previous_coordinator_name",
            "coordinator",
            "coordinator_name",
            "changed_by_name",
            "changed_at",
        ]
        read_only_fields = fields

    def get_previous_coordinator_name(self, obj) -> str | None:
        return _display_name(obj.previous_coordinator)

    def get_coordinator_name(self, obj) -> str | None:
        return _display_name(obj.coordinator)

    def get_changed_by_name(self, obj) -> str:
        return _display_name(obj.changed_by) or "Automatic assignment"


class ChangeLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EventChangeLog
        fields = [
            "id",
            "field",
            "previous_value",
            "new_value",
            "changed_by",
            "changed_by_name",
            "changed_at",
            "significant",
        ]
        read_only_fields = fields

    def get_changed_by_name(self, obj) -> str | None:
        return _display_name(obj.changed_by)


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, trim_whitespace=True, required=False)


class EventRequestSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    coordinator_name = serializers.SerializerMethodField()
    coordinator_email = serializers.CharField(
        source="coordinator.email", read_only=True, default=None
    )
    missing_mandatory_fields = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    rejected_by_name = serializers.SerializerMethodField()
    clarifications = ClarificationSerializer(many=True, read_only=True)
    assignment_history = AssignmentHistorySerializer(many=True, read_only=True)
    updated_by_name = serializers.SerializerMethodField()
    confirmed_by_name = serializers.SerializerMethodField()
    confirmed_arrangements = serializers.SerializerMethodField()

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
            "registration_capacity",
            "registration_opens_at",
            "registration_closes_at",
            "waitlist_enabled",
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
            "coordinator_email",
            "assignment_requires_attention",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "rejected_by",
            "rejected_by_name",
            "rejected_at",
            "rejection_reason",
            "cancellation_reason",
            "confirmed_by_name",
            "confirmed_at",
            "confirmed_arrangements",
            "clarifications",
            "assignment_history",
            "missing_mandatory_fields",
            "is_editable",
            "updated_by_name",
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
            "assignment_requires_attention",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "cancellation_reason",
            "confirmed_at",
            "created_at",
            "updated_at",
        ]

    # The approval decision is visible to internal users only.
    INTERNAL_ONLY_FIELDS = (
        "approved_by",
        "approved_by_name",
        "approved_at",
        "rejected_by",
        "rejected_by_name",
        "assignment_history",
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is None or not request.user.is_internal:
            for field in self.INTERNAL_ONLY_FIELDS:
                data.pop(field, None)
        return data

    def get_approved_by_name(self, obj) -> str | None:
        return _display_name(obj.approved_by)

    def get_updated_by_name(self, obj) -> str | None:
        return _display_name(obj.updated_by)

    def get_confirmed_by_name(self, obj) -> str | None:
        return _display_name(obj.confirmed_by)

    def get_confirmed_arrangements(self, obj) -> dict | None:
        # SCRUM-58 AC5 - shown once the event is confirmed.
        if obj.status not in (EventStatus.CONFIRMED, EventStatus.COMPLETED):
            return None
        from apps.events.confirmation import confirmed_arrangements

        return confirmed_arrangements(obj)

    def get_rejected_by_name(self, obj) -> str | None:
        return _display_name(obj.rejected_by)

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
        return obj.status in (EventStatus.DRAFT, EventStatus.UNDER_REVIEW)

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

    def validate_registration_capacity(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Registration capacity must be at least one place.")
        return value

    def validate(self, attrs):
        def current(field):
            return attrs.get(field, getattr(self.instance, field, None))

        start, end = current("preferred_start"), current("preferred_end")
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"preferred_end": "The event must end after it starts."}
            )
        opens, closes = current("registration_opens_at"), current("registration_closes_at")
        if opens and closes and closes <= opens:
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close after it opens."}
            )
        if closes and end and closes > end:
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close by the end of the event."}
            )
        return attrs


class AttendeeEventSerializer(serializers.ModelSerializer):
    """Public event details that are safe and useful to an Attendee."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()
    places_left = serializers.SerializerMethodField()
    registration_message = serializers.SerializerMethodField()
    waitlist_offered = serializers.SerializerMethodField()
    my_registration = serializers.SerializerMethodField()
    venues = serializers.SerializerMethodField()

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
            "registration_capacity",
            "registration_opens_at",
            "registration_closes_at",
            "places_left",
            "registration_message",
            "waitlist_offered",
            "my_registration",
            "venues",
            "status",
            "status_label",
            "status_description",
            "status_changed_at",
        ]

    def get_status_description(self, obj) -> str:
        return STATUS_DESCRIPTIONS[EventStatus(obj.status)]

    def get_places_left(self, obj) -> int | None:
        return registrations.places_left(obj) if obj.registration_required else None

    def get_registration_message(self, obj) -> str | None:
        # SCRUM-21 AC5 / SCRUM-81 AC2-AC3 - why registration is not open, if it is not.
        return registrations.window_problem(obj)

    def get_waitlist_offered(self, obj) -> bool:
        return registrations.waitlist_offered(obj)

    def get_my_registration(self, obj) -> dict | None:
        # SCRUM-19 AC3 - the Attendee's own registration or waiting-list status.
        request = self.context.get("request")
        mine = request and registrations.existing_for(obj, request.user)
        if not mine:
            return None
        return {"id": mine.pk, "status": mine.status, "status_display": mine.get_status_display()}

    def get_venues(self, obj) -> list[dict]:
        return confirmed_venues(obj)


def _display_name(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.email


class EventQueueSerializer(serializers.ModelSerializer):
    """The narrower shape the coordinator queue needs (US-04.1 AC1).

    Only coordinators reach it, so the approval decision is always included.
    """

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_description = serializers.SerializerMethodField()
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    coordinator_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

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
            "coordinator",
            "coordinator_name",
            "assignment_requires_attention",
            "approved_by_name",
            "approved_at",
        ]

    def get_approved_by_name(self, obj) -> str | None:
        return _display_name(obj.approved_by)

    def get_status_description(self, obj) -> str:
        return STATUS_DESCRIPTIONS[EventStatus(obj.status)]

    def get_coordinator_name(self, obj) -> str | None:
        if obj.coordinator is None:
            return None
        return obj.coordinator.get_full_name() or obj.coordinator.email


class AssignedEventSerializer(EventQueueSerializer):
    """SCRUM-54 - a coordinator's own events, with the next step for each."""

    next_action = serializers.SerializerMethodField()
    requires_action = serializers.SerializerMethodField()

    class Meta(EventQueueSerializer.Meta):
        fields = EventQueueSerializer.Meta.fields + ["next_action", "requires_action"]

    def get_next_action(self, obj) -> str:
        return COORDINATOR_NEXT_ACTIONS[EventStatus(obj.status)][0]

    def get_requires_action(self, obj) -> bool:
        return COORDINATOR_NEXT_ACTIONS[EventStatus(obj.status)][1]
