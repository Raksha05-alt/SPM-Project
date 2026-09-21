from rest_framework.permissions import BasePermission

from apps.core.audit import record_denied


class HasAnyRole(BasePermission):
    """Allow only the roles listed in the view's ``allowed_roles`` attribute.

    Every refusal is written to the audit log, which is what US-01.2 AC4 asks for.
    """

    message = "Your role does not have access to this resource."

    def has_permission(self, request, view) -> bool:
        allowed = getattr(view, "allowed_roles", None)
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        if allowed is None or user.role in allowed:
            return True
        record_denied(
            user,
            action=f"{request.method} {request.path}",
            detail=f"role={user.role} is not in {sorted(allowed)}",
        )
        return False
