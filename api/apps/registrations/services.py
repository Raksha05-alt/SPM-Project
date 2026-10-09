"""SCRUM-21 / 14 / 81 / 19 - registering, withdrawing and the waiting list."""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.registrations.models import ACTIVE_STATUSES, Registration, RegistrationStatus


class RegistrationRefused(Exception):
    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


class NotAllowed(Exception):
    pass


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d %b %Y %H:%M}"


def capacity_of(event: EventRequest) -> int | None:
    return event.registration_capacity or event.expected_attendance


def registered_count(event: EventRequest) -> int:
    return event.registrations.filter(status=RegistrationStatus.REGISTERED).count()


def places_left(event: EventRequest) -> int | None:
    capacity = capacity_of(event)
    if capacity is None:
        return None
    return max(capacity - registered_count(event), 0)


def window_problem(event: EventRequest) -> str | None:
    """Why registration is not open right now, or None when it is (SCRUM-21 AC5, SCRUM-81)."""
    if event.status != EventStatus.CONFIRMED:
        return "Registration is only possible for confirmed events."
    if not event.registration_required:
        return "This event does not take registrations."
    now = timezone.now()
    if event.registration_opens_at and now < event.registration_opens_at:
        return f"Registration opens on {_when(event.registration_opens_at)}."
    closes = event.registration_closes_at or event.preferred_start
    if closes and now >= closes:
        return "Registration for this event has closed."
    return None


def waitlist_offered(event: EventRequest) -> bool:
    """SCRUM-19 AC2 - only a full event with a waiting list offers to join it."""
    return event.waitlist_enabled and window_problem(event) is None and places_left(event) == 0


def existing_for(event: EventRequest, user) -> Registration | None:
    return event.registrations.filter(attendee=user, status__in=ACTIVE_STATUSES).first()


def _lock(event: EventRequest) -> EventRequest:
    # SCRUM-81 AC4 - one registration at a time per event, so the last place goes once.
    return EventRequest.objects.select_for_update().get(pk=event.pk)


@transaction.atomic
def register(event: EventRequest, user, details: dict) -> Registration:
    event = _lock(event)
    problem = window_problem(event)
    if problem:
        raise RegistrationRefused(problem)
    existing = existing_for(event, user)
    if existing and existing.status == RegistrationStatus.REGISTERED:
        raise RegistrationRefused(
            "You are already registered for this event.", existing=existing.pk
        )
    if places_left(event) == 0:
        raise RegistrationRefused(
            "This event is full.", full=True, waitlist_offered=event.waitlist_enabled
        )
    now = timezone.now()
    if existing:
        # A waiting Attendee takes the place that has become free.
        registration = existing
        for field, value in details.items():
            setattr(registration, field, value)
        registration.status = RegistrationStatus.REGISTERED
        registration.registered_at = now
        registration.save()
    else:
        registration = Registration.objects.create(
            event=event, attendee=user, registered_at=now, **details
        )
    notify(
        [user],
        event,
        NotificationKind.REGISTERED,
        f'You are registered for "{event.name}" on {_when(event.preferred_start)}.',
    )
    if places_left(event) == 0:
        # SCRUM-81 AC5.
        notify(
            [event.created_by, event.coordinator],
            event,
            NotificationKind.EVENT_FULL,
            f'Registration for "{event.name}" is full ({capacity_of(event)} places taken).',
        )
    return registration


@transaction.atomic
def join_waitlist(event: EventRequest, user, details: dict) -> Registration:
    """SCRUM-19 AC1 / AC2."""
    event = _lock(event)
    problem = window_problem(event)
    if problem:
        raise RegistrationRefused(problem)
    if not event.waitlist_enabled:
        raise RegistrationRefused("This event does not have a waiting list.")
    existing = existing_for(event, user)
    if existing:
        raise RegistrationRefused(
            f"You are already {existing.get_status_display().lower()} for this event.",
            existing=existing.pk,
        )
    if places_left(event) != 0:
        raise RegistrationRefused("Places are still available; register instead.")
    registration = Registration.objects.create(
        event=event,
        attendee=user,
        status=RegistrationStatus.WAITLISTED,
        waitlisted_at=timezone.now(),
        **details,
    )
    notify(
        [user],
        event,
        NotificationKind.WAITLISTED,
        f'You are on the waiting list for "{event.name}". We will tell you if a place opens.',
    )
    return registration


def offer_places(event: EventRequest) -> list[Registration]:
    """SCRUM-19 AC5 - tell waiting Attendees, in the order they joined, about free places."""
    free = places_left(event) or 0
    if free == 0:
        return []
    waiting = list(
        event.registrations.filter(
            status=RegistrationStatus.WAITLISTED, place_offered_at__isnull=True
        ).order_by("waitlisted_at", "pk")[:free]
    )
    now = timezone.now()
    for registration in waiting:
        registration.place_offered_at = now
        registration.save(update_fields=["place_offered_at", "updated_at"])
    notify(
        [r.attendee for r in waiting],
        event,
        NotificationKind.PLACE_AVAILABLE,
        f'A place has become available for "{event.name}". Register now to take it.',
    )
    return waiting


@transaction.atomic
def withdraw(registration: Registration, user, confirm=False) -> Registration:
    """SCRUM-14 - withdraw, after seeing a summary; the record is kept."""
    event = _lock(registration.event)
    registration = Registration.objects.select_for_update().get(pk=registration.pk)
    if registration.attendee_id != user.pk:
        raise NotAllowed
    if registration.status == RegistrationStatus.WITHDRAWN:
        raise RegistrationRefused("You have already withdrawn from this event.")
    if event.status == EventStatus.COMPLETED or (
        event.preferred_end and event.preferred_end <= timezone.now()
    ):
        raise RegistrationRefused(
            "This event has already taken place, so the registration cannot be withdrawn."
        )
    if not confirm:
        raise RegistrationRefused(
            "Confirm to withdraw.",
            summary={
                "event": event.name,
                "start": event.preferred_start,
                "end": event.preferred_end,
                "status": registration.get_status_display(),
            },
        )
    was_registered = registration.status == RegistrationStatus.REGISTERED
    registration.status = RegistrationStatus.WITHDRAWN
    registration.withdrawn_at = timezone.now()
    registration.save(update_fields=["status", "withdrawn_at", "updated_at"])
    notify(
        [user],
        event,
        NotificationKind.UNREGISTERED,
        f'You have withdrawn from "{event.name}".',
    )
    if was_registered and event.waitlist_enabled:
        offer_places(event)
    return registration


def notify_cancelled(event: EventRequest, user) -> None:
    """SCRUM-18 AC5 - registered Attendees hear that the event is cancelled (cancellation hook)."""
    attendees = [r.attendee for r in event.registrations.filter(status__in=ACTIVE_STATUSES)]
    reason = f" Reason: {event.cancellation_reason}" if event.cancellation_reason else ""
    notify(
        attendees,
        event,
        NotificationKind.STATUS_CHANGED,
        f'"{event.name}" on {_when(event.preferred_start)} has been cancelled.{reason}',
    )
