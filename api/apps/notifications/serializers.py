from rest_framework import serializers

from apps.notifications.models import Notification
from apps.notifications.services import destination


class NotificationSerializer(serializers.ModelSerializer):
    """SCRUM-79 AC5 / SCRUM-82 - the event, what happened, when, and read state.

    ``destination`` is worked out for the signed-in recipient on every read, so
    it reflects their access now rather than when the notice was written.
    """

    event_name = serializers.CharField(source="event.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    is_read = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()

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
            "destination",
        ]
        read_only_fields = fields

    def get_is_read(self, notice) -> bool:
        return notice.read_at is not None

    def get_destination(self, notice):
        found = destination(notice, self.context["request"].user)
        return {"path": found.path, "label": found.label} if found else None
