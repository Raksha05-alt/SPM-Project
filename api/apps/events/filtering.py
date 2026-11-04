"""SCRUM-57: status filtering of an already permission-scoped queryset."""

from rest_framework.exceptions import ValidationError

from apps.core.statuses import EventStatus


def filter_event_statuses(events, params):
    # Repeated keys and comma-separated values have the same OR semantics.
    statuses = {
        part.strip()
        for value in params.getlist("status")
        for part in value.split(",")
        if part.strip()
    }
    invalid = statuses.difference(EventStatus.values)
    if invalid:
        raise ValidationError({"status": ["Unknown status: " + ", ".join(sorted(invalid)) + "."]})
    return events.filter(status__in=statuses) if statuses else events
