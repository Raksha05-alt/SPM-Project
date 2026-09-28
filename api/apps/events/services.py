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
from apps.events.models import EventRequest, EventStatusHistory
from apps.notifications.models import Notification, NotificationKind


class MissingMandatoryFields(Exception):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(f"Missing mandatory fields: {', '.join(fields)}")


class NotAssignedCoordinator(Exception):
    """Raised when someone other than the assigned coordinator tries a coordinator decision."""


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
