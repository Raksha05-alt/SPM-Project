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
* ``withdraw(...)`` - SCRUM-14: the attendee withdraws their own registration
  after seeing ``withdrawal_summary``; the released place goes to ``offer_places``.
* ``join_waitlist(...)`` - SCRUM-19: join the waiting list of a full event.
* ``offer_places(event, occurrence)`` - SCRUM-19 AC5: when places open, tell the
  earliest waiting attendees (FIFO by join time, then id). Notification only:
  nobody is enrolled automatically or holds a seat; registering still needs a
  fresh capacity check. One release (``occurrence``) notifies each person once.

New registrations need: event Confirmed + policy enabled + period open + a
place under the cap. A return to Planning freezes new registrations but keeps
existing ones; nobody is silently withdrawn. Withdrawal stays possible for a
future event in Planning; places are only offered while registration is open.
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
    WaitlistNotice,
)

# A policy may be prepared from approval onwards, and changed until the event ends.
POLICY_EDITABLE = frozenset({EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.CONFIRMED})
POLICY_FIELDS = (
    "enabled",
    "opens_at",
    "closes_at",
    "manually_closed",
    "capacity",
    "waitlist_enabled",
)
# SCRUM-14 - an attendee may withdraw from a future event that is going ahead or replanning.
WITHDRAWABLE = frozenset({EventStatus.CONFIRMED, EventStatus.PLANNING})


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


def waiting_list(event):
    """SCRUM-19 - the event's waiting attendees in FIFO order (join time, then id)."""
    return Registration.objects.filter(event=event, status=RegistrationStatus.WAITLISTED).order_by(
        "registered_at", "pk"
    )


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
    holds_place = mine is not None and mine.status != RegistrationStatus.WITHDRAWN
    position = None
    if mine is not None and mine.status == RegistrationStatus.WAITLISTED:
        position = list(waiting_list(event).values_list("pk", flat=True)).index(mine.pk) + 1
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
        # SCRUM-19 AC1/AC2 - offered only when the event is full, open and allows it.
        "waitlist_offered": bool(
            problem is not None
            and problem.code == "full"
            and policy.waitlist_enabled
            and not holds_place
        ),
        "waitlist_position": position,
        "waiting": waiting_list(event).count(),
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

    # SCRUM-19 - a waiting attendee registers through their own waiting-list
    # entry, after the same fresh capacity check as everyone else.
    waiting = (
        Registration.objects.select_for_update()
        .filter(event=locked, attendee=attendee, status=RegistrationStatus.WAITLISTED)
        .first()
    )
    if waiting is not None:
        registration = waiting
        previous = RegistrationStatus.WAITLISTED
        for field, value in details.items():
            setattr(registration, field, value)
        registration.status = RegistrationStatus.REGISTERED
        registration.save(update_fields=[*details, "status", "updated_at"])
    else:
        registration = Registration.objects.create(
            event=locked, attendee=attendee, registered_at=now, **details
        )
        previous = ""
    RegistrationHistory.objects.create(
        registration=registration,
        from_status=previous,
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
            occurrence=f"full-at:{registration.history.order_by('-pk').first().pk}",
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
    for field in ("enabled", "manually_closed", "waitlist_enabled"):
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
    change = RegistrationPolicyChange.objects.create(
        policy=policy, before=before, after=_snapshot(policy), actor=actor
    )
    # A raised cap, an extension or reopening may free places for the waiting list.
    offer_places(locked, f"policy-change:{change.pk}", policy=policy)
    return policy


# --------------------------------------------------------------------------
# SCRUM-14 - withdrawing
# --------------------------------------------------------------------------


class NotRegistrationOwner(Exception):
    """SCRUM-14 AC6 - only the attendee who registered may withdraw."""


def _withdrawal_problem(event, registration, now) -> RegistrationRefused | None:
    if registration.status == RegistrationStatus.WITHDRAWN:
        return RegistrationRefused("already_withdrawn", "This registration is already withdrawn.")
    if event.status == EventStatus.COMPLETED or (
        event.preferred_end is not None and event.preferred_end <= now
    ):
        return RegistrationRefused(
            "event_over", "This event has already taken place, so you cannot withdraw."
        )
    if event.status not in WITHDRAWABLE:
        return RegistrationRefused(
            "not_withdrawable",
            f"You cannot withdraw from a {event.get_status_display()} event.",
        )
    return None


def withdrawal_summary(registration, actor, now=None) -> dict:
    """SCRUM-14 AC1 - what the attendee sees before confirming a withdrawal."""
    if registration.attendee_id != actor.pk:
        raise NotRegistrationOwner
    event = registration.event
    problem = _withdrawal_problem(event, registration, now or timezone.now())
    return {
        "registration": registration.pk,
        "event": event.pk,
        "event_name": event.name,
        "starts_at": event.preferred_start,
        "ends_at": event.preferred_end,
        "status": registration.status,
        "releases_place": registration.status == RegistrationStatus.REGISTERED,
        "can_withdraw": problem is None,
        "reason": problem.detail if problem else "",
    }


@transaction.atomic
def withdraw(*, registration, actor, confirm=False, now=None) -> Registration:
    """SCRUM-14 - the attendee withdraws their own registration or waiting-list place.

    Needs ``confirm=True`` after the summary (AC1). Refuses someone else's
    registration (AC6) and an event that has taken place (AC4). Keeps the row
    as Withdrawn with its history (AC5). A released place lowers the registered
    count (AC2) and is offered to the waiting list in the same transaction.
    """
    now = now or timezone.now()
    event = EventRequest.objects.select_for_update().get(pk=registration.event_id)
    policy = RegistrationPolicy.objects.select_for_update().filter(event=event).first()
    locked = Registration.objects.select_for_update().get(pk=registration.pk)
    if locked.attendee_id != actor.pk:
        raise NotRegistrationOwner
    problem = _withdrawal_problem(event, locked, now)
    if problem is not None:
        raise problem
    if confirm is not True:
        raise RegistrationRefused(
            "confirm_required", "Confirm the withdrawal to continue.", status=400
        )
    previous = locked.status
    locked.status = RegistrationStatus.WITHDRAWN
    locked.withdrawn_at = now
    locked.save(update_fields=["status", "withdrawn_at", "updated_at"])
    entry = RegistrationHistory.objects.create(
        registration=locked,
        from_status=previous,
        to_status=RegistrationStatus.WITHDRAWN,
        actor=actor,
        changed_at=now,
    )
    what = "registration" if previous == RegistrationStatus.REGISTERED else "waiting-list place"
    notify(
        event=event,
        kind=NotificationKind.REG_WITHDRAWN,
        occurrence=f"withdrawal:{entry.pk}",
        recipients=[actor],
        message=f'You have withdrawn your {what} for "{event.name}".',
    )
    if previous == RegistrationStatus.REGISTERED:
        offer_places(event, f"withdrawal:{entry.pk}", policy=policy, now=now)
    return locked


# --------------------------------------------------------------------------
# SCRUM-19 - the waiting list
# --------------------------------------------------------------------------


@transaction.atomic
def join_waitlist(
    *, event, attendee, full_name="", email="", accessibility_requirements="", now=None
) -> Registration:
    """SCRUM-19 AC1/AC2 - join the waiting list of a full event that allows one.

    Refused while places are still available (they should register), when the
    event is not Confirmed or registration is not open, and for an attendee who
    already holds a registration or waiting-list place.
    """
    if attendee.role != Role.ATTENDEE or not attendee.is_active:
        raise RegistrationRefused("not_attendee", "Only an Attendee can join a waiting list.")
    now = now or timezone.now()
    locked = EventRequest.objects.select_for_update().get(pk=event.pk)
    policy = RegistrationPolicy.objects.select_for_update().filter(event=locked).first()
    if locked.status != EventStatus.CONFIRMED:
        raise RegistrationRefused(
            "not_confirmed", "The waiting list is only available for a confirmed event."
        )
    existing = (
        Registration.objects.filter(event=locked, attendee=attendee)
        .exclude(status=RegistrationStatus.WITHDRAWN)
        .first()
    )
    if existing is not None:
        raise AlreadyRegistered(existing)
    problem = window_problem(policy, now)
    if problem is not None:
        raise problem
    if not policy.waitlist_enabled:
        raise RegistrationRefused("no_waitlist", "This event does not have a waiting list.")
    if not capacity_of(locked, policy).full:
        raise RegistrationRefused(
            "places_available", "Places are still available. Register instead."
        )
    details = _clean_details(full_name, email, accessibility_requirements)
    entry = Registration.objects.create(
        event=locked,
        attendee=attendee,
        status=RegistrationStatus.WAITLISTED,
        registered_at=now,
        **details,
    )
    RegistrationHistory.objects.create(
        registration=entry,
        from_status="",
        to_status=RegistrationStatus.WAITLISTED,
        actor=attendee,
        changed_at=now,
    )
    position = list(waiting_list(locked).values_list("pk", flat=True)).index(entry.pk) + 1
    notify(
        event=locked,
        kind=NotificationKind.WAITLIST_JOINED,
        occurrence=f"waitlist:{entry.pk}",
        recipients=[attendee],
        message=(
            f'You are number {position} on the waiting list for "{locked.name}". '
            "We will tell you if a place becomes available."
        ),
    )
    return entry


def offer_places(event, occurrence: str, *, policy=None, now=None) -> list[Registration]:
    """SCRUM-19 AC5 - tell the earliest waiting attendees that places are free.

    The caller holds the event lock. Notifies as many waiting attendees, in
    FIFO order, as there are free places now; nobody while the event is not
    Confirmed or registration is closed. ``occurrence`` names the release
    (``withdrawal:<history id>``, ``policy-change:<change id>``), so processing
    it again notifies nobody twice. Returns the entries notified now.
    """
    if policy is None:
        policy = RegistrationPolicy.objects.filter(event=event).first()
    if event.status != EventStatus.CONFIRMED or window_problem(policy, now) is not None:
        return []
    free = capacity_of(event, policy).remaining or 0
    if free == 0:
        return []
    notified = []
    for entry in waiting_list(event)[:free]:
        _, created = WaitlistNotice.objects.get_or_create(entry=entry, occurrence=occurrence)
        if not created:
            continue
        notify(
            event=event,
            kind=NotificationKind.PLACE_AVAILABLE,
            occurrence=f"{occurrence}:{entry.pk}",
            recipients=[entry.attendee_id],
            message=(
                f'A place has become available for "{event.name}". Register now to take it: '
                "places go to whoever registers first, and the event may fill again."
            ),
        )
        notified.append(entry)
    return notified
