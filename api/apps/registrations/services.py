"""SCRUM-21 register for an event; SCRUM-81 capacity and registration period.

* ``capacity_of(event)`` - the registration cap, active registrations and places left.
* ``window_problem(policy, now)`` - why the registration period does not admit
  a registration now, or None. The period is ``opens_at <= now < closes_at``,
  plus the organiser's manual closure.
* ``register(...)`` - the attendee registers. Locks the event row, then the
  policy row (the agreed order for registration-only actions), so two attempts
  for the last place serialize: one succeeds, the other is told it is full.
* ``set_policy(...)`` - the organiser's registration controls, kept apart from
  ordinary event editing so they never reopen Confirmed-event edits.

New registrations need: event Confirmed + policy enabled + period open + a
place under the cap. A return to Planning freezes new registrations but keeps
existing ones; nobody is silently withdrawn.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.registrations.models import (
    Registration,
    RegistrationHistory,
    RegistrationPolicy,
    RegistrationPolicyChange,
    RegistrationStatus,
)

# A policy may be prepared from approval onwards, and changed until the event ends.
POLICY_EDITABLE = frozenset({EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CONFIRMED})
POLICY_FIELDS = ("enabled", "opens_at", "closes_at", "manually_closed", "capacity")


class RegistrationRefused(Exception):
    """Registration is not possible now. ``code`` says why; ``extra`` holds details."""

    def __init__(self, code: str, detail: str, **extra):
        self.code = code
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class RegistrationIncomplete(Exception):
    """SCRUM-21 AC2 - required registration information is missing or invalid."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


class AlreadyRegistered(Exception):
    """SCRUM-21 AC3 - the attendee already holds an active registration."""

    def __init__(self, registration: Registration):
        self.registration = registration
        super().__init__("You are already registered for this event.")


class PolicyInvalid(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


class NotEventOrganiser(Exception):
    """Only an organiser of the event's client organisation sets its policy."""


def _local(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Capacity:
    capacity: int | None
    registered: int

    @property
    def remaining(self) -> int | None:
        return None if self.capacity is None else max(self.capacity - self.registered, 0)

    @property
    def full(self) -> bool:
        return self.capacity is not None and self.registered >= self.capacity


def active_registrations(event):
    return Registration.objects.filter(event=event, status=RegistrationStatus.REGISTERED)


def capacity_of(event, policy: RegistrationPolicy | None = None) -> Capacity:
    """SCRUM-81 - the cap and the count of *active* registrations only."""
    if policy is None:
        policy = RegistrationPolicy.objects.filter(event=event).first()
    return Capacity(
        capacity=policy.capacity if policy else None,
        registered=active_registrations(event).count(),
    )


def window_problem(policy: RegistrationPolicy | None, now=None) -> RegistrationRefused | None:
    """SCRUM-81 AC2/AC3 - why the registration period rules out registering now.

    Returns None when registration is enabled, not manually closed, and
    ``opens_at <= now < closes_at`` (either bound may be unset).
    """
    now = now or timezone.now()
    if policy is None or not policy.enabled:
        return RegistrationRefused("not_enabled", "Registration is not available for this event.")
    if policy.manually_closed:
        return RegistrationRefused("closed", "Registration for this event has closed.")
    if policy.opens_at is not None and now < policy.opens_at:
        return RegistrationRefused(
            "not_open",
            f"Registration opens on {_local(policy.opens_at)}.",
            opens_at=policy.opens_at,
        )
    if policy.closes_at is not None and now >= policy.closes_at:
        return RegistrationRefused(
            "closed",
            f"Registration closed on {_local(policy.closes_at)}.",
            closes_at=policy.closes_at,
        )
    return None


def registration_summary(event, user=None, now=None) -> dict:
    """What an attendee sees about registering for one event."""
    policy = RegistrationPolicy.objects.filter(event=event).first()
    count = capacity_of(event, policy)
    problem = None
    if event.status != EventStatus.CONFIRMED:
        problem = RegistrationRefused("not_confirmed", "This event is not open for registration.")
    else:
        problem = window_problem(policy, now)
        if problem is None and count.full:
            problem = RegistrationRefused("full", "This event is full.")
    mine = None
    if user is not None and user.is_authenticated:
        mine = (
            Registration.objects.filter(event=event, attendee=user)
            .order_by("-registered_at", "-pk")
            .first()
        )
    return {
        "enabled": bool(policy and policy.enabled),
        "open": problem is None,
        "reason": problem.detail if problem else "",
        "reason_code": problem.code if problem else "",
        "opens_at": policy.opens_at if policy else None,
        "closes_at": policy.closes_at if policy else None,
        "capacity": count.capacity,
        "remaining": count.remaining,
        "my_status": mine.status if mine else None,
        "my_registration": mine.pk if mine else None,
    }


# --------------------------------------------------------------------------
# Registering
# --------------------------------------------------------------------------


def _clean_details(full_name, email, accessibility_requirements) -> dict:
    """SCRUM-21 AC2 - every missing or invalid item is named."""
    errors: dict[str, str] = {}
    full_name = (full_name or "").strip() if isinstance(full_name, str) else ""
    email = (email or "").strip() if isinstance(email, str) else ""
    if not full_name:
        errors["full_name"] = "Enter your full name."
    if not email:
        errors["email"] = "Enter your email address."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    if accessibility_requirements is None:
        accessibility_requirements = ""
    if not isinstance(accessibility_requirements, str):
        errors["accessibility_requirements"] = "Accessibility requirements must be text."
    if errors:
        raise RegistrationIncomplete(errors)
    return {
        "full_name": full_name,
        "email": email,
        "accessibility_requirements": accessibility_requirements.strip(),
    }


@transaction.atomic
def register(
    *, event, attendee, full_name="", email="", accessibility_requirements="", now=None
) -> Registration:
    """SCRUM-21/81 - record the attendee's registration, or refuse with the reason.

    Order of checks: Attendee role, event Confirmed (21 AC5), an existing
    active registration (21 AC3), the policy and its period (81 AC2/AC3), the
    required details (21 AC2), then capacity (81 AC1). All under the event and
    policy locks, so the count cannot change between the check and the save
    (81 AC4). Taking the last place notifies the organiser and coordinator (81 AC5).
    """
    if attendee.role != Role.ATTENDEE or not attendee.is_active:
        raise RegistrationRefused("not_attendee", "Only an Attendee can register for an event.")
    now = now or timezone.now()
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    policy = RegistrationPolicy.objects.select_for_update().filter(event=locked).first()
    if locked.status != EventStatus.CONFIRMED:
        raise RegistrationRefused(
            "not_confirmed", "Registration is only possible once the event is confirmed."
        )
    existing = active_registrations(locked).filter(attendee=attendee).first()
    if existing is not None:
        raise AlreadyRegistered(existing)
    problem = window_problem(policy, now)
    if problem is not None:
        raise problem
    details = _clean_details(full_name, email, accessibility_requirements)
    count = capacity_of(locked, policy)
    if count.full:
        raise RegistrationRefused("full", "This event is full.", capacity=count.capacity)

    registration = Registration.objects.create(
        event=locked, attendee=attendee, registered_at=now, **details
    )
    RegistrationHistory.objects.create(
        registration=registration,
        from_status="",
        to_status=RegistrationStatus.REGISTERED,
        actor=attendee,
        changed_at=now,
    )
    # SCRUM-21 AC1 - the attendee's confirmation.
    notify(
        event=locked,
        kind=NotificationKind.REGISTERED,
        occurrence=f"registration:{registration.pk}",
        recipients=[attendee],
        message=f'You are registered for "{locked.name}" on {_local(locked.preferred_start)}.',
    )
    # SCRUM-81 AC5 - this registration took the final place.
    if count.capacity is not None and count.registered + 1 >= count.capacity:
        notify(
            event=locked,
            kind=NotificationKind.REGISTRATION_FULL,
            occurrence=f"full-at:{registration.pk}",
            recipients=[locked.created_by, locked.coordinator],
            message=(
                f'Registration for "{locked.name}" is full: all {count.capacity} places are taken.'
            ),
        )
    return registration


# --------------------------------------------------------------------------
# The organiser's policy
# --------------------------------------------------------------------------


def _snapshot(policy: RegistrationPolicy) -> dict:
    snapshot = {}
    for field in POLICY_FIELDS:
        value = getattr(policy, field)
        snapshot[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return snapshot


@transaction.atomic
def set_policy(*, event, actor, **values) -> RegistrationPolicy:
    """The organiser sets or changes the event's registration policy.

    Validates every field; refuses a cap below the current registered count
    rather than removing anyone; records the change with before/after values.
    """
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    if (
        actor.role != Role.EVENT_ORGANISER
        or not actor.is_active
        or actor.organisation_id != locked.organisation_id
    ):
        raise NotEventOrganiser
    if locked.status not in POLICY_EDITABLE:
        raise PolicyInvalid(
            {"event": f"Registration cannot be set up for a {locked.get_status_display()} event."}
        )
    policy, _ = RegistrationPolicy.objects.select_for_update().get_or_create(event=locked)
    before = _snapshot(policy) if policy.changes.exists() else {}
    merged = {field: values.get(field, getattr(policy, field)) for field in POLICY_FIELDS}

    errors: dict[str, str] = {}
    for field in ("enabled", "manually_closed"):
        if not isinstance(merged[field], bool):
            errors[field] = "Choose yes or no."
    for field in ("opens_at", "closes_at"):
        value = merged[field]
        if value is not None and (not hasattr(value, "tzinfo") or timezone.is_naive(value)):
            errors[field] = "Give a date and time with its time zone."
    if (
        "opens_at" not in errors
        and "closes_at" not in errors
        and merged["opens_at"] is not None
        and merged["closes_at"] is not None
        and merged["closes_at"] <= merged["opens_at"]
    ):
        errors["closes_at"] = "Registration must close after it opens."
    capacity = merged["capacity"]
    if capacity is not None and (
        isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1
    ):
        errors["capacity"] = "The registration capacity must be a whole number of at least one."
    elif merged["enabled"] is True and capacity is None:
        errors["capacity"] = "Set a registration capacity before enabling registration."
    elif capacity is not None:
        registered = active_registrations(locked).count()
        if capacity < registered:
            errors["capacity"] = (
                f"{registered} people are already registered; the capacity cannot be lower."
            )
    if errors:
        raise PolicyInvalid(errors)

    for field, value in merged.items():
        setattr(policy, field, value)
    policy.updated_by = actor
    policy.save()
    RegistrationPolicyChange.objects.create(
        policy=policy, before=before, after=_snapshot(policy), actor=actor
    )
    return policy
