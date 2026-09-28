from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.statuses import ATTENDEE_VISIBLE_STATUSES, EventStatus


class CanAccessEventRequest(BasePermission):
    """Object-level rules for an event request.

    An Event Organiser reaches only their own organisation's requests.
    An Event Coordinator reaches anything that has been submitted, never a draft.
    An Attendee has read-only access to confirmed or concluded events, with
    internal planning states filtered out.
    Every refusal is written to the audit log (US-01.2 AC4).
    """

    message = "You do not have access to this event request."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        allowed, reason = self._evaluate(user, request, obj)
        if not allowed:
            record_denied(
                user,
                action=f"{request.method} {request.path}",
                obj=obj,
                detail=reason,
            )
        return allowed

    def _evaluate(self, user, request, obj) -> tuple[bool, str]:
        if user.role == Role.EVENT_ORGANISER:
            if obj.organisation_id != user.organisation_id:
                return False, "event belongs to another client organisation"
            if request.method not in SAFE_METHODS and obj.status != EventStatus.DRAFT:
                return False, f"a {obj.get_status_display()} request is read-only to the client"
            return True, ""

        if user.role == Role.EVENT_COORDINATOR:
            if obj.status == EventStatus.DRAFT:
                return False, "drafts are not visible to ConnectSphere"
            if request.method not in SAFE_METHODS:
                return False, "coordinator write actions arrive in sprint 2"
            return True, ""

        if user.role == Role.ATTENDEE:
            if request.method not in SAFE_METHODS:
                return False, "attendees have read-only access to events"
            if obj.status not in ATTENDEE_VISIBLE_STATUSES:
                return False, "event has not reached an attendee-visible status"
            return True, ""

        return False, f"role {user.role} has no access to event requests"
