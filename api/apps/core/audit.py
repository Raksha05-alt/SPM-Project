"""Audit trail for access decisions.

US-01.2 AC4: a refused request is recorded with the user, the action and the time.

Auditing is deliberately best-effort. A refusal is a security decision that has
already been made by the time we get here, so a failure to write the audit row
must not turn a clean 403 into a 500 and must not leak the failure to the caller.
It is logged instead, so the problem is visible to operators without changing
what the user sees.
"""

import logging

from django.db import transaction

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous (not signed in)"


def record(user, action: str, *, allowed: bool, obj=None, detail: str = "") -> AuditLog | None:
    """Write one audit row.

    Never raises. Returns the row, or ``None`` if it could not be written.

    The write runs inside its own savepoint so that a failure here cannot poison
    an enclosing transaction: the caller's own work stays committable.
    """
    actor = user if getattr(user, "is_authenticated", False) else None
    if actor is None and not detail:
        detail = ANONYMOUS
    try:
        with transaction.atomic():
            return AuditLog.objects.create(
                actor=actor,
                action=action,
                object_type=obj.__class__.__name__ if obj is not None else "",
                object_id=str(getattr(obj, "pk", "") or ""),
                allowed=allowed,
                detail=detail,
            )
    except Exception:
        logger.exception(
            "Could not write audit row: action=%s allowed=%s actor=%s",
            action,
            allowed,
            getattr(actor, "pk", None),
        )
        return None


def record_denied(user, action: str, *, obj=None, detail: str = "") -> AuditLog | None:
    return record(user, action, allowed=False, obj=obj, detail=detail)
