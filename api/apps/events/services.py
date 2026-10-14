"""Behaviour that is not the business of a serializer or a view."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.statuses import (
    REVIEWABLE_STATUSES,
    TERMINAL_STATUSES,
    EventStatus,
    InvalidTransition,
    validate_transition,
)
from apps.events.models import (
    ClarificationComment,
    ClarificationRequest,
    CoordinatorAssignment,
    EventChangeLog,
    EventRequest,
    EventStatusHistory,
)
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


class InvalidReassignment(Exception):
    """Raised when the chosen coordinator cannot take over the event."""


class EventClosed(Exception):
    """Raised when a planning action is attempted on a completed, cancelled or rejected event."""


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


def leads():
    """Week 7 change 5 - every active Event Coordinator Lead sees the unassigned queue."""
    return User.objects.filter(role=Role.COORDINATOR_LEAD, is_active=True)


@transaction.atomic
def submit_event(event: EventRequest, user) -> EventRequest:
    """Submit a draft into the unassigned queue (Week 7 change 5).

    Requests are no longer assigned automatically. They wait, flagged, until an
    Event Coordinator Lead assigns a coordinator. The row lock keeps a repeated
    or concurrent submission from creating a second status change.
    """
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if not locked.is_draft:
        raise InvalidTransition(locked.status, EventStatus.SUBMITTED)
    missing = locked.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    locked.coordinator = None
    locked.assignment_requires_attention = True
    locked.save(update_fields=["coordinator", "assignment_requires_attention"])
    transition_event(locked, EventStatus.SUBMITTED, user)
    name = locked.name
    notify(
        [user],
        locked,
        NotificationKind.SUBMITTED,
        f'"{name}" has been submitted. A ConnectSphere Event Coordinator Lead will assign '
        "your coordinator.",
    )
    notify(
        leads(),
        locked,
        NotificationKind.SUBMITTED,
        f'New request "{name}" from {locked.organisation.name} is waiting to be assigned.',
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
    _resolve_open_clarifications(locked)
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
    if locked.status not in REVIEWABLE_STATUSES:
        raise InvalidTransition(locked.status, EventStatus.UNDER_REVIEW)
    message = (message or "").strip()
    if not message:
        raise MissingClarificationDetails
    if locked.status == EventStatus.SUBMITTED:
        # A further question while already awaiting clarification adds a round
        # to the record without another status change.
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


def _resolve_open_clarifications(event: EventRequest) -> None:
    event.clarifications.filter(resolved_at__isnull=True).update(resolved_at=timezone.now())


@transaction.atomic
def resume_review(event: EventRequest, user) -> EventRequest:
    """The coordinator records that the client has answered (offline) and resumes review."""
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.coordinator_id != user.pk:
        raise NotAssignedCoordinator
    if locked.status != EventStatus.UNDER_REVIEW:
        raise InvalidTransition(locked.status, EventStatus.SUBMITTED)
    transition_event(locked, EventStatus.SUBMITTED, user)
    _resolve_open_clarifications(locked)
    notify(
        [locked.created_by],
        locked,
        NotificationKind.RESUBMITTED,
        f'Your coordinator has recorded your answers and resumed reviewing "{locked.name}".',
    )
    event.refresh_from_db()
    return event


class EmptyComment(Exception):
    """Raised when a clarification comment has no text."""


@transaction.atomic
def add_clarification_comment(event: EventRequest, user, message: str, clarification_id=None):
    """Week 7 clarification - record what was said offline about a clarification.

    The client (their own organisation) and the assigned coordinator may both
    write. The other party is notified so that the record is not missed.
    """
    message = (message or "").strip()
    if not message:
        raise EmptyComment
    # Re-read under the lock: a Lead may have reassigned the event meanwhile.
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    if user.is_organiser:
        if user.organisation_id != event.organisation_id:
            raise NotPermitted
    elif user.is_coordinator:
        if event.coordinator_id != user.pk:
            raise NotAssignedCoordinator
    else:
        raise NotPermitted
    rounds = event.clarifications.all()
    clarification = (
        rounds.filter(pk=clarification_id).first() if clarification_id else rounds.first()
    )
    if clarification is None:
        raise ClarificationNotFound
    comment = ClarificationComment.objects.create(
        clarification=clarification, author=user, message=message
    )
    other = event.coordinator if user.is_organiser else event.created_by
    who = user.get_full_name() or user.email
    notify(
        [other],
        event,
        NotificationKind.CLARIFY_COMMENT,
        f'{who} recorded a clarification note on "{event.name}": {message}',
    )
    return comment


class ClarificationNotFound(Exception):
    """Raised when the event has no clarification round to comment on."""


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


@transaction.atomic
def assign_coordinator(event: EventRequest, user, new_coordinator_id) -> EventRequest:
    """Week 7 change 5 - an Event Coordinator Lead assigns or reassigns an event.

    Every assignment is kept on record (SCRUM-53). The Lead who made it becomes
    the event's supervising Lead. The new coordinator, any previous coordinator
    and the client are told.
    """
    if not user.is_lead:
        raise NotPermitted
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if locked.status == EventStatus.DRAFT:
        raise NotPermitted
    if locked.status in TERMINAL_STATUSES:
        raise EventClosed
    new = User.objects.filter(
        pk=new_coordinator_id, role=Role.EVENT_COORDINATOR, is_active=True
    ).first()
    if new is None:
        raise InvalidReassignment("Choose an active Event Coordinator.")
    if new.pk == locked.coordinator_id:
        raise InvalidReassignment("This coordinator is already assigned to the event.")
    previous = locked.coordinator
    first_assignment = previous is None and not locked.assignment_history.exists()
    locked.coordinator = new
    locked.assigned_by = user
    locked.assigned_at = timezone.now()
    locked.assignment_requires_attention = False
    locked.save(
        update_fields=[
            "coordinator",
            "assigned_by",
            "assigned_at",
            "assignment_requires_attention",
            "updated_at",
        ]
    )
    CoordinatorAssignment.objects.create(
        event=locked, previous_coordinator=previous, coordinator=new, changed_by=user
    )
    name = locked.name or "Untitled event"
    new_name = new.get_full_name() or new.email
    kind = NotificationKind.ASSIGNMENT if first_assignment else NotificationKind.REASSIGNED
    notify(
        [new],
        locked,
        kind,
        f'You are now the coordinator for "{name}". Contact {locked.created_by.email}.',
    )
    if previous:
        notify(
            [previous],
            locked,
            NotificationKind.REASSIGNED,
            f'"{name}" has been reassigned to {new_name}. You no longer coordinate it.',
        )
    notify(
        [locked.created_by],
        locked,
        kind,
        f'{new_name} ({new.email}) is now your coordinator for "{name}".',
    )
    event.refresh_from_db()
    return event


# Kept so that existing callers and tests read naturally.
reassign_event = assign_coordinator


def reopen_planning(event: EventRequest, user, reason: str) -> bool:
    """Week 7 changes 2, 3 and 6 - a confirmed event whose arrangements change goes
    back to Planning, so every approval is obtained again before it is re-confirmed.

    Returns True when the event was re-opened. Call inside a transaction.
    """
    if event.status != EventStatus.CONFIRMED:
        return False
    transition_event(event, EventStatus.PLANNING, user)
    message = (
        f'"{event.name}" is back in planning: {reason} It will be confirmed again once '
        "every arrangement and the safety check are approved."
    )
    recipients = [event.created_by, event.coordinator, event.assigned_by]
    notify(
        [u for u in recipients if u and u.pk != getattr(user, "pk", None)],
        event,
        NotificationKind.STATUS_CHANGED,
        message,
    )
    from apps.registrations.models import RegistrationStatus

    attendees = [
        r.attendee for r in event.registrations.filter(status=RegistrationStatus.REGISTERED)
    ]
    notify(
        attendees,
        event,
        NotificationKind.EVENT_CHANGED,
        f'The arrangements for "{event.name}" are being revised. We will tell you the '
        "confirmed details.",
    )
    return True


# SCRUM-60 / SCRUM-61 - the event information whose changes are kept on record.
TRACKED_FIELDS = (
    "name",
    "purpose",
    "description",
    "preferred_start",
    "preferred_end",
    "expected_attendance",
    "required_layout",
    "accessibility_needs",
    "equipment_notes",
    "registration_required",
    "registration_capacity",
    "registration_opens_at",
    "registration_closes_at",
    "waitlist_enabled",
)


def snapshot(event: EventRequest) -> dict:
    return {field: getattr(event, field) for field in TRACKED_FIELDS}


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def log_changes(event: EventRequest, before: dict, user, significant=frozenset()) -> list[str]:
    """Write one change-history row per field that actually changed; return those fields."""
    changed = [field for field, old in before.items() if getattr(event, field) != old]
    EventChangeLog.objects.bulk_create(
        [
            EventChangeLog(
                event=event,
                field=field,
                previous_value=_as_text(before[field]),
                new_value=_as_text(getattr(event, field)),
                changed_by=user,
                significant=field in significant,
            )
            for field in changed
        ]
    )
    return changed
