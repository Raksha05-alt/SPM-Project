"""Behaviour that is not the business of a serializer or a view."""

from secrets import choice

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import (
    REVIEWABLE_STATUSES,
    EventStatus,
    InvalidTransition,
    validate_transition,
)
from apps.events.models import ClarificationRequest, EventRequest, EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import notify


class MissingMandatoryFields(Exception):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(f"Missing mandatory fields: {', '.join(fields)}")


class MissingClarificationDetails(Exception):
    """Raised when a clarification request does not say what is needed."""


class MissingRejectionReason(Exception):
    """Raised when a rejection does not say why."""


class NotAssignedCoordinator(Exception):
    """Raised when someone other than the assigned coordinator tries a coordinator decision."""


class NotPermitted(Exception):
    """Raised when the user's role or relationship to the event does not allow the action."""


class EventNotFinished(Exception):
    """Raised when an event is marked completed before it has taken place."""


@transaction.atomic
def transition_event(event: EventRequest, target: str, user) -> EventRequest:
    """Move an event to ``target``, recording the change. Raises InvalidTransition."""
    validate_transition(event.status, target)
    previous = event.status
    now = timezone.now()

    event.status = target
    event.status_changed_at = now
    if target == EventStatus.SUBMITTED and event.submitted_at is None:
        event.submitted_at = now
    event.save(update_fields=["status", "status_changed_at", "submitted_at", "updated_at"])

    EventStatusHistory.objects.create(
        event=event, from_status=previous, to_status=target, changed_by=user
    )
    return event


@transaction.atomic
def submit_event(event: EventRequest, user) -> EventRequest:
    """Submit and assign atomically; repeated/concurrent submissions cannot reassign."""
    # Lock only the event row, not the nullable coordinator join used by the view.
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.status == EventStatus.UNDER_REVIEW:
        return _resubmit_after_clarification(locked, event, user)
    if not locked.is_draft:
        raise InvalidTransition(locked.status, EventStatus.SUBMITTED)
    missing = locked.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    candidates = list(
        User.objects.filter(
            role=Role.EVENT_COORDINATOR, is_active=True, coordinator_available=True
        ).order_by("pk")
    )
    locked.coordinator = choice(candidates) if candidates else None
    locked.assignment_requires_attention = not candidates
    locked.save(update_fields=["coordinator", "assignment_requires_attention"])
    transition_event(locked, EventStatus.SUBMITTED, user)
    if locked.coordinator:
        coordinator = locked.coordinator
        name = coordinator.get_full_name() or coordinator.email
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient=user,
                    event=locked,
                    message=f'{name} ({coordinator.email}) is your coordinator for "{locked.name}".',
                ),
                Notification(
                    recipient=coordinator,
                    event=locked,
                    message=f'You have been assigned to "{locked.name}". Contact {user.email}.',
                ),
            ]
        )
    event.refresh_from_db()
    return event


@transaction.atomic
def approve_event(event: EventRequest, user) -> EventRequest:
    """Approve a submitted request, record who decided and when, and tell the client."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if locked.status not in REVIEWABLE_STATUSES:
        raise InvalidTransition(locked.status, EventStatus.APPROVED)
    missing = locked.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    transition_event(locked, EventStatus.APPROVED, user)
    locked.approved_by = user
    locked.approved_at = locked.status_changed_at
    locked.save(update_fields=["approved_by", "approved_at"])
    Notification.objects.create(
        recipient=locked.created_by,
        event=locked,
        kind=NotificationKind.APPROVED,
        message=f'"{locked.name}" has been approved. Venue and equipment planning can begin.',
    )
    event.refresh_from_db()
    return event


@transaction.atomic
def request_clarification(event: EventRequest, user, message: str, fields=()) -> EventRequest:
    """Ask the client for more information and pause the request until they answer."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if locked.status != EventStatus.SUBMITTED:
        raise InvalidTransition(locked.status, EventStatus.UNDER_REVIEW)
    message = (message or "").strip()
    if not message:
        raise MissingClarificationDetails
    transition_event(locked, EventStatus.UNDER_REVIEW, user)
    ClarificationRequest.objects.create(
        event=locked, requested_by=user, message=message, fields=list(fields)
    )
    Notification.objects.create(
        recipient=locked.created_by,
        event=locked,
        kind=NotificationKind.CLARIFICATION,
        message=f'Your coordinator needs more information about "{locked.name}": {message}',
    )
    event.refresh_from_db()
    return event


def _resubmit_after_clarification(locked: EventRequest, event: EventRequest, user) -> EventRequest:
    """Send an answered request back to review, keeping its coordinator and history."""
    missing = locked.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    transition_event(locked, EventStatus.SUBMITTED, user)
    locked.clarifications.filter(resolved_at__isnull=True).update(
        resolved_at=locked.status_changed_at
    )
    if locked.coordinator:
        Notification.objects.create(
            recipient=locked.coordinator,
            event=locked,
            kind=NotificationKind.RESUBMITTED,
            message=f'"{locked.name}" has been updated and resubmitted for review.',
        )
    event.refresh_from_db()
    return event


@transaction.atomic
def reject_event(event: EventRequest, user, reason: str) -> EventRequest:
    """Reject a request ConnectSphere cannot support, keeping the reason on record."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if locked.status not in REVIEWABLE_STATUSES:
        raise InvalidTransition(locked.status, EventStatus.REJECTED)
    reason = (reason or "").strip()
    if not reason:
        raise MissingRejectionReason
    transition_event(locked, EventStatus.REJECTED, user)
    locked.rejected_by = user
    locked.rejected_at = locked.status_changed_at
    locked.rejection_reason = reason
    locked.save(update_fields=["rejected_by", "rejected_at", "rejection_reason"])
    Notification.objects.create(
        recipient=locked.created_by,
        event=locked,
        kind=NotificationKind.REJECTED,
        message=f'ConnectSphere cannot support "{locked.name}". Reason: {reason}',
    )
    event.refresh_from_db()
    return event


def notify_status_change(event: EventRequest, previous: str, actor, extra: str = "") -> None:
    """SCRUM-56 AC4 - tell the people affected by a status change, not the person who made it."""
    message = (
        f'"{event.name or "Untitled event"}" moved from {EventStatus(previous).label} '
        f"to {EventStatus(event.status).label}."
    )
    if extra:
        message = f"{message} {extra}"
    recipients = [u for u in (event.created_by, event.coordinator) if u and u.pk != actor.pk]
    notify(recipients, event, NotificationKind.STATUS_CHANGED, message)


def _check_can_cancel(event: EventRequest, user) -> None:
    if user.is_organiser:
        if user.organisation_id != event.organisation_id:
            raise NotPermitted
        return
    if user.is_coordinator:
        if event.coordinator_id != user.pk:
            raise NotAssignedCoordinator
        return
    raise NotPermitted


@transaction.atomic
def cancel_event(event: EventRequest, user, reason: str = "") -> EventRequest:
    """Cancel an event that has not already ended, been cancelled or been rejected."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    _check_can_cancel(locked, user)
    previous = locked.status
    transition_event(locked, EventStatus.CANCELLED, user)
    locked.cancellation_reason = (reason or "").strip()
    locked.save(update_fields=["cancellation_reason"])
    for release in CANCELLATION_HOOKS:
        release(locked, user)
    extra = f"Reason: {locked.cancellation_reason}" if locked.cancellation_reason else ""
    notify_status_change(locked, previous, user, extra)
    event.refresh_from_db()
    return event


@transaction.atomic
def complete_event(event: EventRequest, user) -> EventRequest:
    """Close a confirmed event once it has taken place."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    validate_transition(locked.status, EventStatus.COMPLETED)
    if locked.preferred_end and locked.preferred_end > timezone.now():
        raise EventNotFinished
    previous = locked.status
    transition_event(locked, EventStatus.COMPLETED, user)
    notify_status_change(locked, previous, user)
    event.refresh_from_db()
    return event


# Other components register what has to be released when an event is
# cancelled (venue bookings, equipment reservations, registrations).
CANCELLATION_HOOKS: list = []
