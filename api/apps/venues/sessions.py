"""SCRUM-87: stable session identity; call mutations under the event lock."""

from django.db import transaction

from apps.core.statuses import EventStatus
from apps.venues.models import BookingStatus, EventSession, SessionKind


def resolve_session(event, session_id=None, name="Main programme", kind=SessionKind.MAIN):
    from apps.venues.bookings import BookingValidationError

    main, _ = EventSession.objects.get_or_create(
        event=event, kind=SessionKind.MAIN, defaults={"name": "Main programme"}
    )
    if session_id is not None:
        session = EventSession.objects.filter(pk=session_id, event=event, is_active=True).first()
        if session is None:
            raise BookingValidationError(
                {"session": "Choose an active session belonging to this event."}
            )
        return session
    if kind not in SessionKind.values:
        raise BookingValidationError({"session_kind": "Choose Main programme or Breakout."})
    if kind == SessionKind.MAIN:
        return main
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise BookingValidationError(
            {"session_name": "Enter a session name of 1 to 100 characters."}
        )
    name = name.strip()
    if EventSession.objects.filter(event=event, name__iexact=name).exists():
        raise BookingValidationError(
            {"session_name": "This session already exists. Select it instead."}
        )
    return EventSession.objects.create(event=event, name=name, kind=kind)


@transaction.atomic
def remove_session(session, actor):
    """Explicitly remove a withdrawn/rejected breakout, without deleting its history."""
    from apps.accounts.models import Role
    from apps.events.history import record_field_changes
    from apps.events.models import EventRequest
    from apps.safety.services import arrangements_changed
    from apps.venues.bookings import BookingValidationError, NotAssignedToEvent

    event = EventRequest.objects.select_for_update().get(pk=session.event_id)
    if actor.role != Role.EVENT_COORDINATOR or event.coordinator_id != actor.pk:
        raise NotAssignedToEvent
    if event.status not in (EventStatus.APPROVED, EventStatus.PLANNING):
        raise BookingValidationError({"event": "Session removal requires an event in planning."})
    locked = EventSession.objects.select_for_update().get(pk=session.pk)
    if locked.kind == SessionKind.MAIN:
        raise BookingValidationError({"session": "The main programme is always required."})
    if (
        locked.bookings.filter(status=BookingStatus.PENDING).exists()
        or locked.bookings.occupying().exists()
    ):
        raise BookingValidationError({"session": "Withdraw this session's active bookings first."})
    if locked.is_active:
        locked.is_active = False
        locked.save(update_fields=["is_active", "updated_at"])
        field = f"venue_session:{locked.pk}:active"
        record_field_changes(event=event, before={field: True}, after={field: False}, actor=actor)
        arrangements_changed(event, f"Session {locked.name} was removed from the programme.", actor)
    return locked
