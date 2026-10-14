from django.utils import timezone

from apps.safety.models import SafetyCheck, SafetyStatus


def approve_safety(event, officer=None):
    """An approved Operational Safety Check, as if the Safety Officer had decided it."""
    return SafetyCheck.objects.create(
        event=event,
        status=SafetyStatus.APPROVED,
        requested_by=event.coordinator,
        decided_by=officer,
        decided_at=timezone.now(),
    )
