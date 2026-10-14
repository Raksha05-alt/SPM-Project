from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.statuses import ATTENDEE_VISIBLE_STATUSES, EventStatus

# Week 7 clarification - organisers cannot edit a request once it is submitted;
# every later edit goes through the coordinator or a change request.
CLIENT_EDITABLE = frozenset({EventStatus.DRAFT})

# Week 7 clarification - the coordinator edits event information before the
# event is confirmed. A confirmed event changes only through a change request.
COORDINATOR_EDITABLE = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
    }
)

# Actions whose own rules (permitted transition, required fields) are enforced
# and audited by the view and service rather than here.
COORDINATOR_ACTIONS = frozenset(
    {
        "approve",
        "reject",
        "request_clarification",
        "resume_review",
        "cancel",
        "complete",
        "confirm",
        "comment",
    }
)
ORGANISER_ACTIONS = frozenset({"cancel", "comment"})
LEAD_ACTIONS = frozenset({"assign", "reassign"})


class CanAccessEventRequest(BasePermission):
    """Object-level rules for an event request.

    An Event Organiser reaches only their own organisation's requests.
    An Event Coordinator reaches only the events assigned to them (Week 7 change 5).
    An Event Coordinator Lead reads every submitted request and assigns them.
    A Safety Officer reads the events sent to them for a safety check.
    An Attendee has read-only access to confirmed or concluded events, with
    internal planning states filtered out.
    Every refusal is written to the audit log (US-01.2 AC4).
    """

    message = "You do not have access to this event request."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        allowed, reason = self._evaluate(user, request, view, obj)
        if not allowed:
            record_denied(
                user,
                action=f"{request.method} {request.path}",
                obj=obj,
                detail=reason,
            )
        return allowed

    def _evaluate(self, user, request, view, obj) -> tuple[bool, str]:
        action = getattr(view, "action", None)
        if user.role == Role.EVENT_ORGANISER:
            if obj.organisation_id != user.organisation_id:
                return False, "event belongs to another client organisation"
            if action in ORGANISER_ACTIONS:
                # The service applies the status rules and audits a refusal.
                return True, ""
            if request.method not in SAFE_METHODS and obj.status not in CLIENT_EDITABLE:
                self.message = (
                    "A submitted request cannot be edited by the client. Ask your coordinator, "
                    "or raise a change request."
                )
                return False, (
                    f"a {obj.get_status_display()} request is read-only to the client; "
                    "changes go through the coordinator"
                )
            return True, ""

        if user.role == Role.EVENT_COORDINATOR:
            if obj.status == EventStatus.DRAFT:
                return False, "drafts are not visible to ConnectSphere"
            if obj.coordinator_id != user.pk:
                return False, "coordinators reach only the events assigned to them"
            if action in COORDINATOR_ACTIONS or request.method in SAFE_METHODS:
                return True, ""
            if action in ("update", "partial_update"):
                if obj.status not in COORDINATOR_EDITABLE:
                    self.message = (
                        f"A {obj.get_status_display()} event cannot be edited directly. "
                        "Changes go through a change request."
                    )
                    return False, (
                        f"a {obj.get_status_display()} event cannot be edited directly; "
                        "raise a change request"
                    )
                return True, ""
            return False, "coordinators cannot perform this action"

        if user.role == Role.COORDINATOR_LEAD:
            if obj.status == EventStatus.DRAFT:
                return False, "drafts are not visible to ConnectSphere"
            if request.method in SAFE_METHODS or action in LEAD_ACTIONS:
                return True, ""
            return False, "leads assign events; the assigned coordinator manages them"

        if user.role == Role.SAFETY_OFFICER:
            if request.method not in SAFE_METHODS:
                return False, "safety officers decide through the safety check"
            if not obj.safety_checks.exists():
                return False, "event has not been sent for a safety check"
            return True, ""

        if user.role == Role.ATTENDEE:
            if request.method not in SAFE_METHODS:
                return False, "attendees have read-only access to events"
            if obj.status not in ATTENDEE_VISIBLE_STATUSES:
                return False, "event has not reached an attendee-visible status"
            return True, ""

        return False, f"role {user.role} has no access to event requests"
