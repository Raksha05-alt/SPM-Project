from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("venues", "0001_initial"),
        ("events", "0006_eventrequest_rejection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VenueShortlistEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("search_criteria", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="venue_shortlist",
                        to="events.eventrequest",
                    ),
                ),
                (
                    "venue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shortlist_entries",
                        to="venues.venue",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "pk"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "venue"), name="unique_event_shortlist_venue"
                    )
                ],
            },
        ),
    ]
