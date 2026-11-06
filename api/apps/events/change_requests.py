"""SCRUM-20 - organisers request a change to a submitted or confirmed event.

Sprint 4 gate INTAKE. A change request records what the organiser wants and
why; it never edits the event. Week 9: organisers cannot edit after submission
and a confirmed event cannot be edited directly, so this is their only route.
The coordinator decides it under SCRUM-78 and an approved change is applied,
through staff review and a fresh Safety check, under SCRUM-80.

The shared contract published here (see docs/event-change-requests.md):

* ``proposed_values`` - typed new values for ``PROPOSABLE_FIELDS`` only,
  validated by the same rules as an event edit, stored JSON-safe.
* ``target_bookings`` / ``target_equipment_requests`` - IDs of this event's own
  venue bookings and equipment requests that the change concerns.
* ``source_values`` / ``source_digest`` / ``source_status`` - the event as it
  was, so later steps can detect a stale request.
"""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.history import jsonable
from apps.events.models import ChangeRequestStatus, EventChangeRequest, EventRequest
from apps.events.services import EDITABLE_FIELDS, snapshot_for_edit

# AC1/AC4 - submitted (in any stage) or confirmed; never a draft, which the
# organiser edits directly, nor a rejected, cancelled or completed event.
OPEN_TO_CHANGE_REQUESTS = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    }
)

# A request in these states still stands; an identical new one is a duplicate.
STILL_OPEN = frozenset(
    {
        ChangeRequestStatus.PENDING,
        ChangeRequestStatus.APPROVED,
        ChangeRequestStatus.IN_REVIEW,
    }
)

# Event fields a change request may propose new values for. Registration
# policy is the organiser's separate control (SCRUM-21/81), not a change here.
PROPOSABLE_FIELDS = tuple(field for field in EDITABLE_FIELDS if field != "registration_required")

# SCRUM-59 AC1 - date, time, attendance, venue requirements and equipment
# requirements: a change to any of them may affect confirmed arrangements.
# Name, purpose and description are ordinary details.
SIGNIFICANT_FIELDS = (
    "preferred_start",
    "preferred_end",
    "expected_attendance",
    "required_layout",
    "accessibility_needs",
    "equipment_notes",
)


def is_significant(proposed_values: dict, target_bookings=(), target_equipment_requests=()) -> bool:
    """SCRUM-59 AC1 - whether a change may affect arrangements, whatever the event's stage."""
    return bool(
        set(proposed_values) & set(SIGNIFICANT_FIELDS)
        or target_bookings
        or target_equipment_requests
    )


class NotEventOrganiser(Exception):
    """Only the event's own organisation may request a change to it."""


class ChangeRequestError(Exception):
    """The request was refused; ``errors`` names every problem. Nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))


def source_snapshot(event: EventRequest) -> tuple[dict, str]:
    """The event's editable values, JSON-safe, and a digest of them."""
    values = {field: jsonable(value) for field, value in snapshot_for_edit(event).items()}
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    return values, digest


def _text(value, field: str, label: str, errors: dict) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors[field] = f"{label} must be text."
        return ""
    if not value.strip():
        errors[field] = f"Enter {label.lower()}."
    return value.strip()


def _proposed(event: EventRequest, proposed, errors: dict) -> dict:
    """Validate proposed values with the event's own field rules; return them JSON-safe."""
    from apps.events.serializers import EventRequestSerializer

    if proposed in (None, ""):
        return {}
    if not isinstance(proposed, dict):
        errors["proposed_values"] = "Proposed values must name event fields."
        return {}
    unknown = sorted(set(proposed) - set(PROPOSABLE_FIELDS))
    if unknown:
        errors["proposed_values"] = (
            "These cannot be changed through a change request: " + ", ".join(unknown) + "."
        )
        return {}
    checked = EventRequestSerializer(instance=event, data=proposed, partial=True)
    if not checked.is_valid():
        for field, messages in checked.errors.items():
            message = messages[0] if isinstance(messages, list) else messages
            errors[f"proposed_values.{field}"] = str(message)
        return {}
    values = {}
    for field in PROPOSABLE_FIELDS:
        if field not in checked.validated_data:
            continue
        value = checked.validated_data[field]
        if field in EventRequest.MANDATORY_FOR_SUBMISSION and value in (None, ""):
            errors[f"proposed_values.{field}"] = "This detail cannot be removed from the event."
        elif value == getattr(event, field):
            errors[f"proposed_values.{field}"] = "This is already the event's current value."
        else:
            values[field] = jsonable(value)
    return values


def _targets(event: EventRequest, ids, field: str, model_rows, label: str, errors: dict) -> list:
    """Every referenced arrangement must exist and belong to this event."""
    if ids in (None, ""):
        return []
    if not isinstance(ids, list) or any(
        isinstance(pk, bool) or not isinstance(pk, int) for pk in ids
    ):
        errors[field] = f"{label} must be a list of IDs."
        return []
    wanted = sorted(set(ids))
    found = set(model_rows.filter(pk__in=wanted).values_list("pk", flat=True))
    if found != set(wanted):
        errors[field] = f"Only this event's own {label.lower()} can be referenced."
        return []
    return wanted


def _recipients(event: EventRequest):
    """AC2 - the assigned coordinator; the Leads while the event is unassigned."""
    from apps.accounts.models import Role, User

    if event.coordinator_id and event.coordinator.is_active:
        return [event.coordinator]
    return list(User.objects.filter(role=Role.EVENT_COORDINATOR_LEAD, is_active=True))


@transaction.atomic
def request_change(
    *,
    event: EventRequest,
    requested_by,
    description=None,
    reason=None,
    proposed_values=None,
    target_bookings=None,
    target_equipment_requests=None,
) -> EventChangeRequest:
    """SCRUM-20 - save a Pending change request and notify whoever must review it.

    Locks the event first (the shared lock order). Refuses, with nothing saved,
    a user outside the event's organisation, an event that is a draft or is
    rejected, cancelled or completed (AC4), a missing description (AC3) or
    reason, and proposed values or references that are invalid. The event's own
    values are never changed (Week 9: requests, not edits).
    """
    from apps.equipment.models import EquipmentRequest
    from apps.notifications.models import NotificationKind
    from apps.notifications.services import notify
    from apps.venues.models import VenueBooking

    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if (
        requested_by.organisation_id is None
        or locked.organisation_id != requested_by.organisation_id
    ):
        raise NotEventOrganiser
    if locked.status not in OPEN_TO_CHANGE_REQUESTS:
        if locked.status == EventStatus.DRAFT:
            message = "This request has not been submitted yet; edit the draft instead."
        else:
            message = f"A change cannot be requested for a {locked.get_status_display()} event."
        raise ChangeRequestError({"event": message})

    errors: dict[str, str] = {}
    description = _text(description, "description", "A description of the change", errors)
    reason = _text(reason, "reason", "The reason for the change", errors)
    proposed = _proposed(locked, proposed_values, errors)
    bookings = _targets(
        locked,
        target_bookings,
        "target_bookings",
        VenueBooking.objects.filter(event=locked),
        "Venue bookings",
        errors,
    )
    equipment = _targets(
        locked,
        target_equipment_requests,
        "target_equipment_requests",
        EquipmentRequest.objects.filter(plan__event=locked),
        "Equipment requests",
        errors,
    )
    if errors:
        raise ChangeRequestError(errors)
    # Final E2E defect 3: a double submit made two identical open requests.
    # The event row is locked above, so two simultaneous submits are serialised
    # and the second one sees the first here. Identical = same description,
    # proposed values and referenced arrangements.
    duplicate = EventChangeRequest.objects.filter(
        event=locked,
        status__in=STILL_OPEN,
        description__iexact=description,
        proposed_values=proposed,
    ).order_by("pk")
    for open_request in duplicate:
        if sorted(open_request.target_bookings or []) == sorted(bookings) and sorted(
            open_request.target_equipment_requests or []
        ) == sorted(equipment):
            raise ChangeRequestError(
                {
                    "proposed_values": (
                        f"Change request #{open_request.pk} already asks for this change "
                        f"and is {open_request.get_status_display()}."
                    )
                }
            )

    values, digest = source_snapshot(locked)
    change = EventChangeRequest.objects.create(
        event=locked,
        requested_by=requested_by,
        description=description,
        reason=reason,
        proposed_values=proposed,
        target_bookings=bookings,
        target_equipment_requests=equipment,
        source_values=values,
        source_digest=digest,
        source_status=locked.status,
        status=ChangeRequestStatus.PENDING,
        significant=is_significant(proposed, bookings, equipment),
    )
    name = requested_by.get_full_name() or requested_by.email
    notify(
        event=locked,
        kind=NotificationKind.CHANGE_REQUESTED,
        occurrence=f"change-request:{change.pk}",
        recipients=_recipients(locked),
        message=(
            f'{name} requested a change to "{locked.name}": {description[:120]}'
            + ("…" if len(description) > 120 else "")
        ),
        skip=requested_by,
    )
    return change


# --------------------------------------------------------------------------
# SCRUM-78 AC5 - the assigned coordinator approves or rejects, with a reason
# --------------------------------------------------------------------------


class NotAssignedCoordinator(Exception):
    """Only the event's assigned coordinator decides its change requests."""


class ChangeDecisionError(Exception):
    """The decision was refused; ``errors`` names every problem. Nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))


class ChangeAlreadyDecided(Exception):
    """The request is no longer Pending (a replay or another tab decided it)."""

    def __init__(self, change: EventChangeRequest):
        self.change = change
        super().__init__(f"This change request is already {change.get_status_display()}.")


class StaleChangeRequest(Exception):
    """The event changed since the request was made, so it cannot be approved as it stands."""


DECISIONS = {"APPROVE": ChangeRequestStatus.APPROVED, "REJECT": ChangeRequestStatus.REJECTED}


def _decision_recipients(change: EventChangeRequest, event: EventRequest) -> list:
    """AC5 - the Event Organiser who asked (and the event's creator, if different)."""
    return [user for user in (change.requested_by, event.created_by) if user and user.is_active]


def _staff_notices(
    change: EventChangeRequest, event: EventRequest, assessment: dict, actor
) -> None:
    """SCRUM-59 AC3 - an approved significant change reaches the staff whose arrangements it affects.

    Notice only: the staff review work itself is created when the change is
    applied (SCRUM-80). Nothing is moved or released here.
    """
    from apps.accounts.models import Role, User
    from apps.notifications.models import NotificationKind
    from apps.notifications.services import notify

    groups = (
        (Role.VENUE_STAFF, "venue", assessment["venue_bookings"], "venue bookings"),
        (Role.TECHNICAL_SUPPORT, "technical", assessment["equipment"], "equipment"),
    )
    for role, audience, affected, what in groups:
        if not affected:
            continue
        notify(
            event=event,
            kind=NotificationKind.CHANGE_DECIDED,
            occurrence=f"change-approved:{change.pk}:{audience}",
            recipients=User.objects.filter(role=role, is_active=True),
            message=(
                f'An approved change to "{event.name}" affects its {what}: {change.description[:120]}'
                + ("…" if len(change.description) > 120 else "")
                + " It will be sent to you for review before anything changes."
            ),
            skip=actor,
        )


@transaction.atomic
def decide_change(*, change: EventChangeRequest, actor, decision=None, reason=None):
    """SCRUM-78 AC5 - record the coordinator's approval or rejection and its reason.

    Locks the event, then the request. Refuses, with nothing saved, anyone but
    the event's assigned coordinator, a request that is no longer Pending, a
    missing decision or reason, and an approval of a request whose event has
    changed since it was made (it can still be rejected). An approval of a
    significant change also tells the affected Venue Staff and Technical Support
    (SCRUM-59 AC3). The decision never moves bookings, reservations,
    registrations or event fields: an approved change is applied under SCRUM-80.
    Returns ``(change, assessment)``.
    """
    from apps.core.audit import record
    from apps.events.impact import assess_change
    from apps.notifications.models import NotificationKind
    from apps.notifications.services import notify

    event = EventRequest.objects.select_for_update().get(pk=change.event_id)
    locked = EventChangeRequest.objects.select_for_update().get(pk=change.pk)
    if event.coordinator_id is None or event.coordinator_id != actor.pk:
        raise NotAssignedCoordinator
    if locked.status != ChangeRequestStatus.PENDING:
        raise ChangeAlreadyDecided(locked)

    errors: dict[str, str] = {}
    target = DECISIONS.get(decision) if isinstance(decision, str) else None
    if target is None:
        errors["decision"] = "Choose whether to approve or reject the change."
    reason = _text(reason, "reason", "The reason for your decision", errors)
    if errors:
        raise ChangeDecisionError(errors)

    assessment = assess_change(locked, event=event)
    if target == ChangeRequestStatus.APPROVED:
        if event.status not in OPEN_TO_CHANGE_REQUESTS:
            raise ChangeDecisionError(
                {"event": f"A {event.get_status_display()} event cannot take an approved change."}
            )
        if assessment["stale"]:
            raise StaleChangeRequest

    now = timezone.now()
    locked.status = target
    locked.status_changed_at = now
    locked.decided_by = actor
    locked.decided_at = now
    locked.decision_reason = reason
    locked.save(
        update_fields=[
            "status",
            "status_changed_at",
            "decided_by",
            "decided_at",
            "decision_reason",
            "updated_at",
        ]
    )
    verb = "approved" if target == ChangeRequestStatus.APPROVED else "rejected"
    notify(
        event=event,
        kind=NotificationKind.CHANGE_DECIDED,
        occurrence=f"change-decision:{locked.pk}",
        recipients=_decision_recipients(locked, event),
        message=(
            f'Your change request for "{event.name}" was {verb}. Reason: {reason[:200]}'
            + ("…" if len(reason) > 200 else "")
        ),
        skip=actor,
    )
    if target == ChangeRequestStatus.APPROVED and locked.significant:
        _staff_notices(locked, event, assessment, actor)
    record(
        actor,
        f"Change request {locked.pk} {verb}",
        allowed=True,
        obj=event,
        detail=reason,
    )
    return locked, assessment
