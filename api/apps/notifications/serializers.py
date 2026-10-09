from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """SCRUM-79 AC5 - which event, what happened and when; SCRUM-82 - read or not."""

    event_name = serializers.CharField(source="event.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event",
            "event_name",
            "kind",
            "kind_label",
            "message",
            "created_at",
            "read_at",
            "is_read",
        ]
        read_only_fields = fields

    def get_is_read(self, obj) -> bool:
        return obj.read_at is not None
