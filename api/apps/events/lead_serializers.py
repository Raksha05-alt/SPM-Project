from rest_framework import serializers

from apps.accounts.models import User
from apps.core.statuses import EventStatus
from apps.events.models import CoordinatorAssignment, EventRequest
from apps.events.serializers import EventRequestSerializer, _display_name


class AssignmentInputSerializer(serializers.Serializer):
    coordinator_id = serializers.IntegerField(min_value=1)
    expected_revision = serializers.IntegerField(min_value=0)


class CoordinatorChoiceSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email", "coordinator_available"]
        read_only_fields = fields

    def get_name(self, obj):
        return _display_name(obj)


class AssignmentHistorySerializer(serializers.ModelSerializer):
    previous_coordinator_name = serializers.SerializerMethodField()
    coordinator_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.SerializerMethodField()
    previous_supervising_lead_name = serializers.SerializerMethodField()

    class Meta:
        model = CoordinatorAssignment
        fields = [
            "id",
            "revision",
            "previous_coordinator",
            "previous_coordinator_name",
            "coordinator",
            "coordinator_name",
            "assigned_by",
            "assigned_by_name",
            "previous_supervising_lead",
            "previous_supervising_lead_name",
            "assigned_at",
        ]
        read_only_fields = fields

    def get_previous_coordinator_name(self, obj):
        return _display_name(obj.previous_coordinator)

    def get_coordinator_name(self, obj):
        return _display_name(obj.coordinator)

    def get_assigned_by_name(self, obj):
        return _display_name(obj.assigned_by)

    def get_previous_supervising_lead_name(self, obj):
        return _display_name(obj.previous_supervising_lead)


def can_assign(event):
    return event.status not in {EventStatus.DRAFT, EventStatus.COMPLETED, EventStatus.CANCELLED}


class LeadQueueSerializer(serializers.ModelSerializer):
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    coordinator_name = serializers.SerializerMethodField()
    supervising_lead_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    can_assign = serializers.SerializerMethodField()

    class Meta:
        model = EventRequest
        fields = [
            "id",
            "name",
            "purpose",
            "organisation_name",
            "status",
            "status_label",
            "preferred_start",
            "preferred_end",
            "expected_attendance",
            "submitted_at",
            "coordinator",
            "coordinator_name",
            "supervising_lead",
            "supervising_lead_name",
            "assignment_revision",
            "can_assign",
        ]
        read_only_fields = fields

    def get_coordinator_name(self, obj):
        return _display_name(obj.coordinator)

    def get_supervising_lead_name(self, obj):
        return _display_name(obj.supervising_lead)

    def get_can_assign(self, obj):
        return can_assign(obj)


class LeadEventSerializer(EventRequestSerializer):
    assignment_history = serializers.SerializerMethodField()
    can_assign = serializers.SerializerMethodField()

    class Meta(EventRequestSerializer.Meta):
        fields = [*EventRequestSerializer.Meta.fields, "assignment_history", "can_assign"]
        read_only_fields = fields

    def get_assignment_history(self, obj):
        rows = obj.assignment_history.select_related(
            "previous_coordinator", "coordinator", "assigned_by", "previous_supervising_lead"
        )
        return AssignmentHistorySerializer(rows, many=True).data

    def get_can_assign(self, obj):
        return can_assign(obj)
