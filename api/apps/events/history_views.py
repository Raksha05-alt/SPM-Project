"""SCRUM-60 - the internal, read-only change history of an event."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.permissions import HasAnyRole
from apps.core.statuses import EventStatus
from apps.events.models import EventFieldChange, EventRequest

# Internal users who plan or supervise the event. Organisers and Attendees
# (and staff with no planning role) are refused and audited by HasAnyRole.
HISTORY_READERS = frozenset({Role.EVENT_COORDINATOR, Role.EVENT_COORDINATOR_LEAD})


def _display(field: str, value, labels: dict) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field == "required_layout":
        return labels.get(value, value)
    if field in ("preferred_start", "preferred_end"):
        try:
            moment = timezone.localtime(timezone.datetime.fromisoformat(value))
        except (TypeError, ValueError):
            return str(value)
        return moment.strftime("%d %b %Y, %H:%M")
    return str(value)


class FieldChangeSerializer(serializers.ModelSerializer):
    """AC1 - the field, previous and new value, the user and the time."""

    field_label = serializers.SerializerMethodField()
    before_display = serializers.SerializerMethodField()
    after_display = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    source_label = serializers.CharField(source="get_source_display")

    class Meta:
        model = EventFieldChange
        fields = [
            "id",
            "field",
            "field_label",
            "before",
            "after",
            "before_display",
            "after_display",
            "values_recorded",
            "actor_name",
            "source",
            "source_label",
            "changed_at",
        ]
        read_only_fields = fields

    def get_field_label(self, entry) -> str:
        try:
            return str(EventRequest._meta.get_field(entry.field).verbose_name).capitalize()
        except Exception:  # a field no longer on the model keeps its stored name
            return entry.field.replace("_", " ").capitalize()

    def _value(self, entry, value) -> str:
        if not entry.values_recorded:
            return "Not recorded"
        return _display(entry.field, value, self.context["layouts"])

    def get_before_display(self, entry) -> str:
        return self._value(entry, entry.before)

    def get_after_display(self, entry) -> str:
        return self._value(entry, entry.after)

    def get_actor_name(self, entry):
        if entry.actor is None:
            return None
        return entry.actor.get_full_name() or entry.actor.email


class EventChangeHistoryView(APIView):
    """GET /api/events/<id>/change-history/ - newest first (AC2). Reads only (AC4)."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    allowed_roles = HISTORY_READERS

    def http_method_not_allowed(self, request, *args, **kwargs):
        # AC4 - an attempt to edit or delete history is refused and audited.
        record_denied(
            request.user,
            action=f"{request.method} {request.path}",
            detail="change history is append-only",
        )
        return super().http_method_not_allowed(request, *args, **kwargs)

    def get(self, request, event_id):
        from apps.venues.layouts import label_map

        event = get_object_or_404(EventRequest, pk=event_id)
        user = request.user
        reason = None
        if event.status == EventStatus.DRAFT:
            reason = "drafts are not visible to ConnectSphere"
        elif user.is_coordinator and event.coordinator_id != user.pk:
            reason = "event is not assigned to this coordinator"
        if reason:
            record_denied(user, action=f"GET {request.path}", obj=event, detail=reason)
            raise PermissionDenied("You do not have access to this event's change history.")
        entries = event.field_changes.select_related("actor").order_by("-changed_at", "-pk")
        data = FieldChangeSerializer(entries, many=True, context={"layouts": label_map()}).data
        return Response({"event": event.pk, "changes": data})
