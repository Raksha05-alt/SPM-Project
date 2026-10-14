from rest_framework import serializers

from apps.safety.models import DECISIONS, SafetyCheck


def _name(user):
    if user is None:
        return None
    return user.get_full_name() or user.email


class SafetyCheckSummarySerializer(serializers.ModelSerializer):
    """The state of a check, as shown on the event to internal staff."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SafetyCheck
        fields = [
            "id",
            "event",
            "status",
            "status_display",
            "requested_by_name",
            "requested_at",
            "request_note",
            "decided_by_name",
            "decided_at",
            "comment",
            "superseded_at",
            "superseded_reason",
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj):
        return _name(obj.decided_by)


class SafetyCheckSerializer(SafetyCheckSummarySerializer):
    """A check with the facts the Safety Officer reviews."""

    event_name = serializers.CharField(source="event.name", read_only=True)
    event_status = serializers.CharField(source="event.get_status_display", read_only=True)
    organisation_name = serializers.CharField(source="event.organisation.name", read_only=True)
    coordinator_name = serializers.SerializerMethodField()
    current_facts = serializers.SerializerMethodField()

    class Meta(SafetyCheckSummarySerializer.Meta):
        fields = SafetyCheckSummarySerializer.Meta.fields + [
            "event_name",
            "event_status",
            "organisation_name",
            "coordinator_name",
            "facts",
            "current_facts",
        ]
        read_only_fields = fields

    def get_coordinator_name(self, obj):
        return _name(obj.event.coordinator)

    def get_current_facts(self, obj) -> dict | None:
        # A pending check shows the arrangements as they stand now.
        if obj.status != "PENDING":
            return None
        from apps.safety.services import safety_facts

        return safety_facts(obj.event)


class SafetyRequestInputSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class SafetyDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[d.value for d in DECISIONS],
        error_messages={"required": "Choose approve, reject or request changes."},
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")
