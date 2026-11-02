"""Keep both published booking notification migrations and their choices."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0009_venue_decided_kind"),
        ("notifications", "0009_alter_notification_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("ASSIGNMENT", "Coordinator assigned"),
                    ("APPROVED", "Request approved"),
                    ("CLARIFICATION", "Clarification requested"),
                    ("RESUBMITTED", "Request resubmitted"),
                    ("REJECTED", "Request rejected"),
                    ("SAFETY_REQUESTED", "Safety check requested"),
                    ("SAFETY_DECIDED", "Safety check decided"),
                    ("SAFETY_SUPERSEDED", "Safety check no longer applies"),
                    ("PLANNING_REOPENED", "Event returned to planning"),
                    ("CLARIFICATION_NOTE", "Clarification note added"),
                    ("REVIEW_RESUMED", "Review resumed"),
                    ("VENUE_REQUESTED", "Venue booking requested"),
                    ("VENUE_DECIDED", "Venue booking decided"),
                    ("VENUE_WITHDRAWN", "Venue booking withdrawn"),
                ],
                default="ASSIGNMENT",
                max_length=20,
            ),
        ),
    ]
