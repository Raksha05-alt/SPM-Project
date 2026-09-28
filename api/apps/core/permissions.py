"""Role-level permission classes.

US-01.2 AC3: a request for an action outside the caller's permissions is refused
outright, never partially served.
US-01.2 AC4: every refusal is recorded.
"""

from rest_framework.permissions import BasePermission

from apps.core.audit import record_denied


class HasAnyRole(BasePermission):
    """Allow only the roles listed in the view's ``allowed_roles`` attribute.

    This class also refuses unauthenticated callers, and records that refusal.
    It must therefore be listed **before** ``IsAuthenticated`` in a view's
    ``permission_classes``: DRF stops at the first class that returns ``False``,
    so an earlier ``IsAuthenticated`` would refuse anonymous callers silently and
    nothing would reach the audit log.
    """

    message = "Your role does not have access to this resource."

    def has_permission(self, request, view) -> bool:
        user = request.user
        action = f"{request.method} {request.path}"

        if not getattr(user, "is_authenticated", False):
            # AC4 - an unauthenticated probe is still a refused request, and it
            # is the one most worth having a record of.
            record_denied(user, action=action, detail="not signed in")
            return False

        allowed = getattr(view, "allowed_roles", None)
        if allowed is None or user.role in allowed:
            return True

        record_denied(
            user,
            action=action,
            detail=f"role={user.role} is not in {sorted(allowed)}",
        )
        return False


class IsInternalStaff(BasePermission):
    """Allow only ConnectSphere's own staff.

    US-01.2 AC2 - internal planning information is not reachable by an Event
    Organiser or an Attendee. The audit log is exactly such information, so this
    class guards it.
    """

    message = "This information is restricted to ConnectSphere staff."

    def has_permission(self, request, view) -> bool:
        user = request.user
        action = f"{request.method} {request.path}"

        if not getattr(user, "is_authenticated", False):
            record_denied(user, action=action, detail="not signed in")
            return False

        if user.is_internal:
            return True

        record_denied(
            user,
            action=action,
            detail=f"role={user.role} is external; internal planning information refused",
        )
        return False
