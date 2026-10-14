"""Seed the layout catalogue with the layouts that were fixed before the Week 7
clarification, so existing venues, events and bookings keep valid codes."""

from django.db import migrations

STARTER = [
    ("CLASSROOM", "Classroom", "Rows of tables facing the front."),
    ("THEATRE", "Theatre", "Rows of chairs facing a stage or screen."),
    ("BOARDROOM", "Boardroom", "One table with seating around it."),
    ("BANQUET", "Banquet", "Round tables for dining."),
    ("EXHIBITION", "Exhibition", "Open floor with booths or stands."),
]


def seed(apps, schema_editor):
    LayoutType = apps.get_model("venues", "LayoutType")
    for code, name, description in STARTER:
        LayoutType.objects.get_or_create(
            code=code, defaults={"name": name, "description": description}
        )


class Migration(migrations.Migration):
    dependencies = [("venues", "0004_week7_buffers_holds_layouts")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
