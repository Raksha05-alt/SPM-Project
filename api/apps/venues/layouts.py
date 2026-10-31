"""SCRUM-91 - the room layout catalogue's shared rules.

Venues, event requests and venue bookings store layout codes. Every write that
chooses layouts calls ``claim_layouts`` inside its transaction, and catalogue
retire/delete lock the same rows, so a layout cannot be retired or deleted at
the same moment someone selects it:

* ``claim_layouts`` takes a shared row lock (FOR SHARE) on the chosen layouts,
  so concurrent selections do not block one another.
* retire and delete take an exclusive lock (FOR UPDATE), wait for those
  selections to commit, then re-check usage.
"""

import re

from django.db import connection

from apps.venues.models import LayoutType

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")

# The layouts the catalogue starts with (also seeded by migration 0006).
SEED_LAYOUTS = [
    ("CLASSROOM", "Classroom"),
    ("THEATRE", "Theatre"),
    ("BOARDROOM", "Boardroom"),
    ("BANQUET", "Banquet"),
    ("EXHIBITION", "Exhibition"),
]


def ensure_seed_layouts() -> None:
    """Create any missing seed layout. Used by tests after a database flush."""
    for order, (code, name) in enumerate(SEED_LAYOUTS, start=1):
        LayoutType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": order})


class LayoutChoiceError(Exception):
    """A chosen layout is unknown or retired; ``message`` says which."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def active_names() -> list[str]:
    return list(LayoutType.objects.filter(is_active=True).values_list("name", flat=True))


def _choose_from() -> str:
    return f"Choose from {', '.join(active_names())}."


def label_map() -> dict[str, str]:
    """Every layout's current name by code, retired ones included (AC2)."""
    return dict(LayoutType.objects.values_list("code", "name"))


def cached_label_map(context) -> dict[str, str]:
    """``label_map`` looked up once per serializer context (one query per response)."""
    if context is None:
        return label_map()
    labels = context.get("_layout_labels")
    if labels is None:
        labels = context["_layout_labels"] = label_map()
    return labels


def catalogue_order() -> dict[str, int]:
    return {
        code: index for index, code in enumerate(LayoutType.objects.values_list("code", flat=True))
    }


def check_choice(codes, *, keep=()) -> list[str]:
    """Return ``codes`` de-duplicated in catalogue order, or raise LayoutChoiceError.

    SCRUM-91 AC4 - an unknown or retired layout is refused. A layout already on
    the record being edited (``keep``) stays allowed even if it was retired since.
    This check does not lock; use ``claim_layouts`` inside the write transaction.
    """
    codes = [c for c in codes if c]
    known = {lt.code: lt for lt in LayoutType.objects.filter(code__in=codes)}
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise LayoutChoiceError(f"Unknown layout: {', '.join(map(str, unknown))}. {_choose_from()}")
    retired = [c for c in codes if not known[c].is_active and c not in set(keep)]
    if retired:
        names = ", ".join(known[c].name for c in dict.fromkeys(retired))
        raise LayoutChoiceError(f"Retired layout: {names}. {_choose_from()}")
    order = catalogue_order()
    return sorted(dict.fromkeys(codes), key=order.__getitem__)


def claim_layouts(codes, *, keep=()) -> list[str]:
    """``check_choice`` while holding a shared lock on the chosen layout rows.

    Call inside the transaction that saves the record, so a concurrent retire or
    delete waits for this save and then sees the new reference.
    """
    codes = [c for c in codes if c]
    if codes:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM {LayoutType._meta.db_table} "
                "WHERE code = ANY(%s) ORDER BY id FOR SHARE",
                [list(dict.fromkeys(codes))],
            )
    return check_choice(codes, keep=keep)


def layout_usage(code: str) -> dict[str, int]:
    """How many venues, event requests and venue bookings use ``code`` (AC3)."""
    from apps.events.models import EventRequest
    from apps.venues.models import Venue, VenueBooking

    return {
        "venues": Venue.objects.supporting_layout(code).count(),
        "event_requests": EventRequest.objects.filter(required_layout=code).count(),
        "venue_bookings": VenueBooking.objects.filter(layout=code).count(),
    }
