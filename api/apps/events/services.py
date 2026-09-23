"""Behaviour that is not the business of a serializer or a view."""

from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus, validate_transition
from apps.events.models import EventRequest, EventStatusHistory


class MissingMandatoryFields(Exception):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(f"Missing mandatory fields: {', '.join(fields)}")


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


def submit_event(event: EventRequest, user) -> EventRequest:
    """US-02.2 - submit a draft once every mandatory field is present."""
    missing = event.missing_mandatory_fields()
    if missing:
        raise MissingMandatoryFields(missing)
    # Revalidate saved values: a previously valid start may now be in the past.
    from apps.events.serializers import EventRequestSerializer

    values = {field: getattr(event, field) for field in event.MANDATORY_FOR_SUBMISSION}
    validator = EventRequestSerializer(event, data=values, partial=True)
    validator.is_valid(raise_exception=True)
    return transition_event(event, EventStatus.SUBMITTED, user)
