from rest_framework.permissions import BasePermission

from apps.core.audit import record_denied
from apps.core.statuses import EventStatus


class CanAccessVenueShortlist(BasePermission):
    """SCRUM-89: coordinator reads and writes follow current event ownership."""

    message = "Only the assigned coordinator may access this event's shortlist."

    def has_object_permission(self, request, view, event):
        allowed = event.status != EventStatus.DRAFT and event.coordinator_id == request.user.pk
        if not allowed:
            record_denied(
                request.user,
                action=f"{request.method} {request.path}",
                obj=event,
                detail="draft event or coordinator is not assigned to this event",
            )
        return allowed
