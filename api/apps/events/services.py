"""Behaviour that is not the business of a serializer or a view."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.audit import record
from apps.core.statuses import (
    REVIEWABLE_STATUSES,
    EventStatus,
    InvalidTransition,
    validate_transition,
)
from apps.events.models import (
    ClarificationRequest,
    CoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
)
from apps.notifications.models import Notification, NotificationKind


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


class AssignmentConflict(Exception):
    """The assignment changed or the event cannot be assigned."""


class InvalidCoordinator(Exception):
    """An assignment target must be an active Event Coordinator."""


class NotCoordinatorLead(Exception):
    """Only an active Coordinator Lead can assign or reassign."""


@transaction.atomic
def assign_coordinator(event, coordinator_id, user, expected_revision):
    """Compare-and-set under a row lock; each actual change is one occurrence."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if not User.objects.filter(
        pk=user.pk, role=Role.EVENT_COORDINATOR_LEAD, is_active=True
    ).exists():
        raise NotCoordinatorLead
    if locked.status in {EventStatus.DRAFT, EventStatus.COMPLETED, EventStatus.CANCELLED}:
        raise AssignmentConflict("Draft, completed and cancelled events cannot be assigned.")
    if locked.assignment_revision != expected_revision:
        raise AssignmentConflict("The assignment changed. Reload the event before assigning it.")
    coordinator = (
        # Account fields must stay current, but assignment history also takes
        # FK key-share locks on previous owners. NO KEY UPDATE permits those
        # checks when two Leads concurrently swap owners of different events.
        User.objects.select_for_update(no_key=True)
        .filter(pk=coordinator_id, role=Role.EVENT_COORDINATOR, is_active=True)
        .first()
    )
    if coordinator is None:
        raise InvalidCoordinator("Choose an active Event Coordinator.")
    if locked.coordinator_id == coordinator.pk:
        event.refresh_from_db()
        return None
    previous = locked.coordinator
    assignment = CoordinatorAssignment.objects.create(
        event=locked,
        previous_coordinator=previous,
        coordinator=coordinator,
        assigned_by=user,
        previous_supervising_lead=locked.supervising_lead,
        revision=locked.assignment_revision + 1,
    )
    locked.coordinator = coordinator
    locked.supervising_lead = user
    locked.assignment_revision = assignment.revision
    locked.assignment_requires_attention = False
    locked.save(
        update_fields=[
            "coordinator",
            "supervising_lead",
            "assignment_revision",
            "assignment_requires_attention",
            "updated_at",
        ]
    )
    recipients = {
        person.pk: person for person in (coordinator, previous, locked.created_by) if person
    }
    name = coordinator.get_full_name() or coordinator.email
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=recipient,
                event=locked,
                assignment=assignment,
                kind=NotificationKind.ASSIGNMENT,
                message=f'{name} ({coordinator.email}) is now the coordinator for "{locked.name}".',
            )
            for recipient in recipients.values()
        ]
    )
    record(
        user,
        f"POST /api/events/{locked.pk}/assign-coordinator/",
        allowed=True,
        obj=assignment,
        detail=f"Assignment revision {assignment.revision}",
    )
    event.refresh_from_db()
    return assignment


@transaction.atomic
def transition_event(event: EventRequest, target: str, user) -> EventRequest:
    """Move an event to ``target``, recording the change.

    Raises InvalidTransition, or ConfirmationBlocked (SCRUM-90 AC5) when the
    target is Confirmed and ``confirmation_gaps`` is not empty, including a
    missing, pending or out-of-date safety check.
    """
    validate_transition(event.status, target)
    if target == EventStatus.CONFIRMED:
        # Imported here: the safety app builds on events, not the other way round.
        from apps.safety.services import ensure_can_confirm

        ensure_can_confirm(event)
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
    """Submit atomically into the Lead's unassigned queue (SCRUM-89)."""
    # Lock only the event row, not the nullable coordinator join used by the view.
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.status == EventStatus.UNDER_REVIEW:
        return _resubmit_after_clarification(locked, event, user)
    if not locked.is_draft:
        raise InvalidTransition(locked.status, EventStatus.SUBMITTED)
    missing = locked.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    locked.coordinator = None
    locked.supervising_lead = None
    locked.assignment_requires_attention = True
    locked.save(update_fields=["coordinator", "supervising_lead", "assignment_requires_attention"])
    transition_event(locked, EventStatus.SUBMITTED, user)
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
