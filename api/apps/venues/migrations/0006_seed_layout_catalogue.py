"""SCRUM-91 - seed the layout catalogue from the former fixed list.

The five codes venues, event requests and bookings already store keep working
unchanged. Any other code already saved (which the old fixed list should have
prevented) is kept as a retired entry, so existing records stay readable.
"""

from django.db import migrations

SEED = [
    ("CLASSROOM", "Classroom"),
    ("THEATRE", "Theatre"),
    ("BOARDROOM", "Boardroom"),
    ("BANQUET", "Banquet"),
    ("EXHIBITION", "Exhibition"),
]


def seed(apps, schema_editor):
    LayoutType = apps.get_model("venues", "LayoutType")
    Venue = apps.get_model("venues", "Venue")
    VenueBooking = apps.get_model("venues", "VenueBooking")
    EventRequest = apps.get_model("events", "EventRequest")

    for order, (code, name) in enumerate(SEED, start=1):
        LayoutType.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": order, "is_active": True}
        )

    in_use = set()
    for layouts in Venue.objects.values_list("layouts", flat=True):
        in_use.update(code for code in layouts or [] if isinstance(code, str) and code)
    in_use.update(
        EventRequest.objects.exclude(required_layout="").values_list("required_layout", flat=True)
    )
    in_use.update(VenueBooking.objects.exclude(layout="").values_list("layout", flat=True))

    known = set(LayoutType.objects.values_list("code", flat=True))
    names = {n.lower() for n in LayoutType.objects.values_list("name", flat=True)}
    order = len(SEED)
    for code in sorted(in_use - known):
        order += 1
        name = code.replace("_", " ").title()
        if name.lower() in names:
            name = f"{name} ({code})"
        names.add(name.lower())
        LayoutType.objects.create(code=code, name=name, sort_order=order, is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("venues", "0005_layout_catalogue"),
        ("events", "0008_required_layout_from_catalogue"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
