"""One place that decides how a notification row is written.

Callers pass every user who should hear about something. Duplicates and empty
slots (an unassigned coordinator, for example) are dropped here, so each
recipient gets exactly one message per change.
"""

from apps.notifications.models import Notification, NotificationKind


def notify(recipients, event, kind: str, message: str) -> list[Notification]:
    unique = []
    seen = set()
    for user in recipients:
        if user is None or user.pk in seen:
            continue
        seen.add(user.pk)
        unique.append(user)
    return Notification.objects.bulk_create(
        [Notification(recipient=user, event=event, kind=kind, message=message) for user in unique]
    )


__all__ = ["notify", "NotificationKind"]
