"""SCRUM-60 - recover earlier SCRUM-61 edits from the audit log.

Those audit entries ("Event <id> edited", detail "Changed: a, b") named the
changed fields, the user and the time, but never the values. Each becomes a
history entry with ``values_recorded=False``; no value is invented.
"""

import re

from django.db import migrations

ACTION = re.compile(r"^Event (\d+) edited$")


def forwards(apps, schema_editor):
    AuditLog = apps.get_model("core", "AuditLog")
    EventRequest = apps.get_model("events", "EventRequest")
    EventFieldChange = apps.get_model("events", "EventFieldChange")
    existing = set(EventRequest.objects.values_list("pk", flat=True))
    entries = []
    for log in AuditLog.objects.filter(allowed=True, action__startswith="Event ").order_by("pk"):
        match = ACTION.match(log.action)
        if not match or not log.detail.startswith("Changed: "):
            continue
        event_id = int(match.group(1))
        if event_id not in existing:
            continue
        for field in log.detail[len("Changed: ") :].split(", "):
            if field:
                entries.append(
                    EventFieldChange(
                        event_id=event_id,
                        field=field.strip(),
                        before=None,
                        after=None,
                        values_recorded=False,
                        actor_id=log.actor_id,
                        source="LEGACY_AUDIT",
                        changed_at=log.created_at,
                    )
                )
    EventFieldChange.objects.bulk_create(entries)


def backwards(apps, schema_editor):
    apps.get_model("events", "EventFieldChange").objects.filter(source="LEGACY_AUDIT").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("events", "0011_event_field_change_history"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
