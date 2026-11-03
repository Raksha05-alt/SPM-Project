"""SCRUM-60 - the transactional field-change history writer.

``record_field_changes`` is mandatory business history: call it inside the
action's transaction. If it fails, the action fails and rolls back. (Access
logging through ``apps.core.audit.record`` is deliberately best-effort and is
not a substitute.) Later producers - SCRUM-20/80 change requests and resource
review outcomes - call the same writer with their own ``ChangeSource``.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.events.models import ChangeSource, EventFieldChange, EventRequest


def jsonable(value):
    """A JSON-safe form of a model value: aware datetimes as ISO 8601."""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def record_field_changes(
    *,
    event: EventRequest,
    before: dict,
    after: dict,
    actor,
    source: str = ChangeSource.EVENT_EDIT,
    at: datetime.datetime | None = None,
) -> list[EventFieldChange]:
    """Append one entry per field whose value changed; return them.

    Only keys present in both ``before`` and ``after`` are compared, in
    ``before``'s order. A no-op save writes nothing. All entries of one call
    share one timestamp, so a single edit reads as one change.
    """
    at = at or timezone.now()
    entries = [
        EventFieldChange(
            event=event,
            field=field,
            before=jsonable(before[field]),
            after=jsonable(after[field]),
            actor=actor,
            source=source,
            changed_at=at,
        )
        for field in before
        if field in after and before[field] != after[field]
    ]
    return EventFieldChange.objects.bulk_create(entries)
