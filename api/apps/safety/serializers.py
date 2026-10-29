from rest_framework import serializers

from apps.safety.models import CURRENT_STATUSES, DECISIONS, SafetyCheck, SafetyStatus


def _name(user):
    if user is None:
        return None
    return user.get_full_name() or user.email


class SafetyCheckSerializer(serializers.ModelSerializer):
    """A check as listed to internal staff."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True)
    event_status = serializers.CharField(source="event.status", read_only=True)
    event_status_display = serializers.CharField(source="event.get_status_display", read_only=True)
    event_start = serializers.DateTimeField(source="event.preferred_start", read_only=True)
    organisation_name = serializers.CharField(source="event.organisation.name", read_only=True)
    coordinator_name = serializers.SerializerMethodField()
    requested_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    is_stale = serializers.SerializerMethodField()

    class Meta:
        model = SafetyCheck
        fields = [
            "id",
            "event",
            "event_name",
            "event_status",
            "event_status_display",
            "event_start",
            "organisation_name",
            "coordinator_name",
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
            "is_stale",
        ]
        read_only_fields = fields

    def get_coordinator_name(self, obj):
        return _name(obj.event.coordinator)

    def get_requested_by_name(self, obj):
        return _name(obj.requested_by)

    def get_decided_by_name(self, obj):
        return _name(obj.decided_by)

    def get_is_stale(self, obj) -> bool:
        """True when a pending or approved check no longer matches the arrangements."""
        if obj.status not in CURRENT_STATUSES:
            return False
        from apps.safety.services import is_stale

        return is_stale(obj)


class SafetyCheckDetailSerializer(SafetyCheckSerializer):
    """AC2 - a check with the facts the Safety Officer reviews.

    ``facts`` is the snapshot taken when the check was requested; for a pending
    check ``current_facts`` shows the arrangements as they stand now.
    """

    current_facts = serializers.SerializerMethodField()

    class Meta(SafetyCheckSerializer.Meta):
        fields = SafetyCheckSerializer.Meta.fields + ["facts", "current_facts"]
        read_only_fields = fields

    def get_current_facts(self, obj) -> dict | None:
        if obj.status != SafetyStatus.PENDING:
            return None
        from apps.safety.services import safety_facts

        return safety_facts(obj.event)


class SafetyRequestInputSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class SafetyDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[d.value for d in DECISIONS],
        error_messages={
            "required": "Choose approve, reject or request changes.",
            "invalid_choice": "Choose approve, reject or request changes.",
        },
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)
