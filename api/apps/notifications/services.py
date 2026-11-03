"""SCRUM-79/82 - the one notification writer, and what a notice may open.

Producers call ``notify()`` inside their own business transaction, so a notice
is saved only if the action is (and rolls back with it). Each call names the
**business occurrence** it reports, derived from a persisted record
(``status_occurrence(event)``, ``f"assignment:{assignment.pk}"`` ...).
Uniqueness is recipient + occurrence: replaying one action never duplicates a
notice, while a later genuine occurrence of the same kind on the same event
(a second confirmation, a reallocation) notifies again.

Never pass a random or time-based key: a retry would then look like a new
occurrence. In-app delivery is the release-1 channel; there is no email.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import ATTENDEE_VISIBLE_STATUSES, EventStatus
from apps.notifications.models import Notification, NotificationTarget


class MissingOccurrence(ValueError):
    """A notice was written without a stable business occurrence."""


def status_occurrence(event) -> str:
    """The occurrence of the event's latest status change.

    Call straight after ``transition_event``: each transition writes one
    ``EventStatusHistory`` row, so its id identifies that occurrence.
    """
    latest = event.status_history.order_by("-pk").values_list("pk", flat=True).first()
    if latest is None:
        raise MissingOccurrence(f"Event {event.pk} has no status history.")
    return f"event-status:{latest}"


def notify(
    *,
    event,
    kind: str,
    occurrence: str,
    recipients: Iterable,
    message: str,
    target_type: str = "",
    target_id: int | None = None,
    assignment=None,
    skip=None,
) -> list[Notification]:
    """Save one notice per distinct recipient for this occurrence.

    ``recipients`` may hold users, user ids or None (ignored). ``skip`` leaves
    out the person who acted. A recipient already holding a notice for this
    occurrence is left as they are. Returns the notices created now.
    """
    occurrence = (occurrence or "").strip()
    if not occurrence:
        raise MissingOccurrence("Every notice needs a stable business occurrence.")
    # Scoped by kind, so two kinds of notice about one record never collide.
    occurrence = f"{kind}:{occurrence}"
    skip_id = getattr(skip, "pk", skip)
    ids: list[int] = []
    for person in recipients:
        pk = getattr(person, "pk", person)
        if pk is not None and pk != skip_id and pk not in ids:
            ids.append(pk)
    if not ids:
        return []
    existing = set(
        Notification.objects.filter(recipient_id__in=ids, occurrence=occurrence).values_list(
            "recipient_id", flat=True
        )
    )
    created = [
        Notification(
            recipient_id=pk,
            event=event,
            kind=kind,
            occurrence=occurrence,
            message=message,
            target_type=target_type,
            target_id=target_id,
            assignment=assignment,
        )
        for pk in ids
        if pk not in existing
    ]
    # The unique constraint is the backstop for a concurrent replay.
    Notification.objects.bulk_create(created, ignore_conflicts=True)
    return created


def unread_count(user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


@transaction.atomic
def mark_read(notification_id: int, user) -> Notification:
    """Mark the recipient's own notice read. Repeating it changes nothing.

    Someone else's notice is reported as missing, so its existence is not disclosed.
    """
    notice = Notification.objects.select_for_update().get(pk=notification_id, recipient=user)
    if notice.read_at is None:
        notice.read_at = timezone.now()
        notice.save(update_fields=["read_at"])
    return notice


# --------------------------------------------------------------------------
# AC3 of SCRUM-82 - where a notice may take its recipient, decided now
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    path: str
    label: str


def destination(notice: Notification, user) -> Destination | None:
    """The screen this notice opens for ``user`` today, or None.

    Decided from the recipient's *current* role and relationship to the event,
    mirroring each screen's own permission rules. A notice kept after a
    reassignment or a role change therefore opens nothing it no longer may.
    """
    if not user.is_active:
        return None
    event = notice.event
    role = user.role
    if role == Role.EVENT_ORGANISER:
        if event.organisation_id == user.organisation_id:
            return Destination(f"/organiser/requests/{event.pk}", "Open your request")
        return None
    if event.status == EventStatus.DRAFT and role != Role.ATTENDEE:
        return None
    if role == Role.EVENT_COORDINATOR:
        if event.coordinator_id == user.pk:
            return Destination(f"/coordinator/events/{event.pk}", "Open the event")
        return None
    if role == Role.EVENT_COORDINATOR_LEAD:
        return Destination(f"/lead/events/{event.pk}", "Open the event")
    if role == Role.SAFETY_OFFICER:
        if notice.target_type == NotificationTarget.SAFETY_CHECK and notice.target_id:
            from apps.safety.models import SafetyCheck

            if SafetyCheck.objects.filter(pk=notice.target_id, event=event).exists():
                return Destination(f"/safety/checks/{notice.target_id}", "Open the safety check")
        return Destination("/safety", "Open safety checks")
    if role == Role.VENUE_STAFF:
        return Destination("/venues/requests", "Open booking requests")
    if role == Role.TECHNICAL_SUPPORT:
        return Destination(f"/equipment/plans/{event.pk}", "Open the equipment plan")
    if role == Role.ATTENDEE and event.status in ATTENDEE_VISIBLE_STATUSES:
        return Destination("/events", "Open events")
    return None
