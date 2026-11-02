from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import Role
from apps.core.audit import record_denied
from apps.core.statuses import ATTENDEE_VISIBLE_STATUSES, EventStatus

# SCRUM-61 AC6 / SCRUM-92 AC3 - after submission the client cannot edit; agreed
# changes are made by the assigned coordinator on the client's behalf.
CLIENT_EDITABLE = frozenset({EventStatus.DRAFT})

# SCRUM-61 AC5 - the assigned coordinator edits a request up to Planning.
# AC3 - Confirmed, Completed and Cancelled events are not edited directly; a
# Confirmed event changes only through a change request (SCRUM-80).
COORDINATOR_EDITABLE = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
    }
)

# Coordinator decisions the views check and audit themselves.
COORDINATOR_ACTIONS = frozenset(
    {"approve", "reject", "request_clarification", "resume_review", "clarification_notes"}
)
EDIT_ACTIONS = frozenset({"update", "partial_update"})


class CanAccessEventRequest(BasePermission):
    """Object-level rules for an event request.

    An Event Organiser reaches only their own organisation's requests.
    Coordinators reach only their assigned submitted events. Leads can read
    submitted events to allocate them; their only write is assignment.
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
        if user.role == Role.EVENT_ORGANISER:
            if obj.organisation_id != user.organisation_id:
                return False, "event belongs to another client organisation"
            # SCRUM-92 - the client may add a note to a clarification; the
            # service checks it is open. Deleting stays draft-only (see the view).
            if getattr(view, "action", None) == "clarification_notes":
                return True, ""
            if request.method not in SAFE_METHODS and obj.status not in CLIENT_EDITABLE:
                return False, f"a {obj.get_status_display()} request is read-only to the client"
            return True, ""

        if user.role == Role.EVENT_COORDINATOR:
            if obj.status == EventStatus.DRAFT:
                return False, "drafts are not visible to ConnectSphere"
            if obj.coordinator_id != user.pk:
                return False, "event is not assigned to this coordinator"
            action = getattr(view, "action", None)
            if action in COORDINATOR_ACTIONS:
                # The view refuses anyone but the assigned coordinator, and audits it.
                return True, ""
            if action in EDIT_ACTIONS:
                if obj.status in COORDINATOR_EDITABLE:
                    return True, ""
                if obj.status == EventStatus.CONFIRMED:
                    return False, "a Confirmed event changes only through a change request"
                return False, f"a {obj.get_status_display()} event cannot be edited"
            if request.method not in SAFE_METHODS:
                return False, "this action is not available to coordinators"
            return True, ""

        if user.role == Role.EVENT_COORDINATOR_LEAD:
            if obj.status == EventStatus.DRAFT:
                return False, "drafts are not visible to ConnectSphere"
            if (
                request.method in SAFE_METHODS
                or getattr(view, "action", None) == "assign_coordinator"
            ):
                return True, ""
            return (
                False,
                "Leads allocate events; coordinator actions belong to the assigned coordinator",
            )

        if user.role == Role.ATTENDEE:
            if request.method not in SAFE_METHODS:
                return False, "attendees have read-only access to events"
            if obj.status not in ATTENDEE_VISIBLE_STATUSES:
                return False, "event has not reached an attendee-visible status"
            return True, ""

        return False, f"role {user.role} has no access to event requests"
