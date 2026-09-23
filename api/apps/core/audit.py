from apps.core.models import AuditLog


def record(user, action: str, *, allowed: bool, obj=None, detail: str = "") -> AuditLog:
    """Write one audit row. Never raises: auditing must not break a request."""
    actor = user if getattr(user, "is_authenticated", False) else None
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "") or ""),
        allowed=allowed,
        detail=detail,
    )


def record_denied(user, action: str, *, obj=None, detail: str = "") -> AuditLog:
    return record(user, action, allowed=False, obj=obj, detail=detail)
