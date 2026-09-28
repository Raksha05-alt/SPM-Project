from rest_framework import serializers

from apps.core.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only view of one access decision.

    ``actor_name`` is resolved here rather than exposing the user object, so that
    reading the audit log never becomes a way to enumerate accounts.
    """

    actor_name = serializers.SerializerMethodField()
    actor_role = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "actor_name",
            "actor_role",
            "action",
            "object_type",
            "object_id",
            "allowed",
            "detail",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj) -> str:
        if obj.actor is None:
            return "Anonymous"
        return obj.actor.get_full_name() or obj.actor.email

    def get_actor_role(self, obj) -> str | None:
        if obj.actor is None:
            return None
        return obj.actor.get_role_display()
