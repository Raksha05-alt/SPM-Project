"""SCRUM-59 AC1 - flag change requests that may affect arrangements.

Requests made before this field existed are classified from what they
recorded (their proposed fields and referenced arrangements), using the same
rule as new requests. Nothing else about them changes.
"""

from django.db import migrations, models

# Kept here so the migration does not depend on later code changes.
SIGNIFICANT_FIELDS = (
    "preferred_start",
    "preferred_end",
    "expected_attendance",
    "required_layout",
    "accessibility_needs",
    "equipment_notes",
)


def classify_existing(apps, schema_editor):
    ChangeRequest = apps.get_model("events", "EventChangeRequest")
    for change in ChangeRequest.objects.all().only(
        "pk", "proposed_values", "target_bookings", "target_equipment_requests"
    ):
        significant = bool(
            set(change.proposed_values or {}) & set(SIGNIFICANT_FIELDS)
            or change.target_bookings
            or change.target_equipment_requests
        )
        if significant:
            ChangeRequest.objects.filter(pk=change.pk).update(significant=True)


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0015_venueperiodreview"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventchangerequest",
            name="significant",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(classify_existing, migrations.RunPython.noop),
    ]
