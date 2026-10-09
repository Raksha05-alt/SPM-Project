"""SCRUM-20 raise and SCRUM-78 decide a change request; approval applies it (SCRUM-80)."""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.impact import apply_change
from apps.events.models import ChangeRequest, ChangeRequestStatus, EventChangeLog, EventRequest
from apps.events.services import NotAssignedCoordinator, snapshot
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

# SCRUM-20 AC1 / AC4 - submitted up to confirmed; never closed events or drafts.
CHANGEABLE_STATUSES = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    }
)


class ChangeRefused(Exception):
    def __init__(self, detail: str, status: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status = status


@transaction.atomic
def raise_change_request(event: EventRequest, user, data: dict) -> ChangeRequest:
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if event.status not in CHANGEABLE_STATUSES:
        raise ChangeRefused(
            f"A change cannot be requested for a {event.get_status_display().lower()} event."
        )
    start = data.get("proposed_start") or event.preferred_start
    end = data.get("proposed_end") or event.preferred_end
    if (data.get("proposed_start") or data.get("proposed_end")) and start and end and end <= start:
        raise ChangeRefused("The event must end after it starts.", status=400)
    change = ChangeRequest.objects.create(event=event, requested_by=user, **data)
    notify(
        [event.coordinator],
        event,
        NotificationKind.CHANGE_REQUESTED,
        f'{user.get_full_name() or user.email} requested a change to "{event.name}": '
        f"{change.description}",
    )
    return change


@transaction.atomic
def decide(change: ChangeRequest, user, *, approve: bool, reason: str) -> ChangeRequest:
    """SCRUM-78 AC5 - approve or reject with a reason; approval updates the event."""
    change = ChangeRequest.objects.select_for_update().get(pk=change.pk)
    event = EventRequest.objects.select_for_update().get(pk=change.event_id)
    if event.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if change.status != ChangeRequestStatus.PENDING:
        raise ChangeRefused(
            f"This change request has already been {change.get_status_display().lower()}."
        )
    reason = (reason or "").strip()
    if not reason:
        raise ChangeRefused("Enter a reason for your decision.", status=400)
    if approve and event.status not in CHANGEABLE_STATUSES:
        raise ChangeRefused(
            f"The event is {event.get_status_display().lower()}; the change cannot be applied."
        )
    change.status = ChangeRequestStatus.APPROVED if approve else ChangeRequestStatus.REJECTED
    change.decided_by = user
    change.decided_at = timezone.now()
    change.decision_reason = reason
    change.save()
    EventChangeLog.objects.create(
        event=event,
        field="Change request",
        previous_value=change.description,
        new_value=f"{change.get_status_display()}: {reason}",
        changed_by=user,
        significant=approve,
    )
    if approve:
        before = snapshot(event)
        for field, value in change.proposed_values().items():
            setattr(event, field, value)
        event.updated_by = user
        event.save()
        apply_change(event, before, user, change_request=change)
    notify(
        [event.created_by],
        event,
        NotificationKind.CHANGE_DECIDED,
        f'Your change request for "{event.name}" was {change.get_status_display().lower()}. '
        f"Reason: {reason}",
    )
    return change
