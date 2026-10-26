from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.audit import record_denied
from apps.core.statuses import EventStatus


class CanAccessVenueShortlist(BasePermission):
    """Keep baseline submitted-event reads; restrict planning writes to the owner."""

    message = "Only the assigned coordinator may change this event's shortlist."

    def has_object_permission(self, request, view, event):
        allowed = event.status != EventStatus.DRAFT and (
            request.method in SAFE_METHODS or event.coordinator_id == request.user.pk
        )
        if not allowed:
            record_denied(
                request.user,
                action=f"{request.method} {request.path}",
                obj=event,
                detail="draft event or coordinator is not assigned to this event",
            )
        return allowed
