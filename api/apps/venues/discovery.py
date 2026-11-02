"""SCRUM-64/68, G12: fresh venue matches using shared booking/block checks."""

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.core.audit import record
from apps.core.statuses import TERMINAL_STATUSES
from apps.venues.availability import availability, within_operating_hours
from apps.venues.layouts import label_map
from apps.venues.models import Venue, VenueShortlistEntry
from apps.venues.occupancy import occupancy_prefetch

AVAILABILITY_LIMITATION = (
    "Availability reflects approved bookings, recorded date-specific blocks and operating hours "
    "for the selected period. Search results do not reserve a venue. "
    "Venue Staff recheck availability before approving a request."
)

DISCOVERY_CAPABILITIES = {
    "availability_integrated": True,
    "booking_occupancy_integrated": True,
    "date_blocks_integrated": True,
    "holds_integrated": False,
}


def assess_venue(venue, criteria, labels=None):
    """Re-evaluate current venue data against saved/entered search criteria."""
    checks = []

    def check(key, label, matches, message):
        checks.append(
            {
                "key": key,
                "label": label,
                "result": "MATCH" if matches else "UNMET",
                "message": message,
            }
        )

    check(
        "operational_status",
        "Operational status",
        venue.in_service,
        "In service." if venue.in_service else "This venue is out of service.",
    )
    if (attendance := criteria.get("attendance")) is not None:
        check(
            "attendance",
            "Capacity",
            venue.capacity >= attendance,
            f"Required: {attendance}; recorded capacity: {venue.capacity}.",
        )
    if layout := criteria.get("layout"):
        name = (label_map() if labels is None else labels).get(layout, layout)
        check("layout", "Room layout", layout in venue.layouts, f"Required layout: {name}.")
    if facilities := criteria.get("facilities"):
        offered = {item.strip().casefold() for item in venue.facilities}
        missing = [item for item in facilities if item.casefold() not in offered]
        check(
            "facilities",
            "Facilities",
            not missing,
            "Missing: " + ", ".join(missing)
            if missing
            else "All required facilities are recorded.",
        )
    has_period = bool(criteria.get("start") and criteria.get("end"))
    if has_period:
        start = parse_datetime(criteria["start"])
        end = parse_datetime(criteria["end"])
        within_hours = within_operating_hours(venue, start, end)
        period = availability(venue, start, end)
        check(
            "operating_hours",
            "Operating hours",
            bool(within_hours),
            "The period fits the recorded operating hours."
            if within_hours
            else "The period is outside recorded operating hours or the hours are missing.",
        )
        blocked = period["blocks"]
        conflicts = period["conflicts"]
        check(
            "approved_bookings",
            "Approved bookings",
            not conflicts,
            "Conflicting event(s): " + ", ".join(str(b["event_id"]) for b in conflicts)
            if conflicts
            else "No approved booking overlaps this period.",
        )
        check(
            "date_blocks",
            "Recorded date-specific blocks",
            not blocked,
            "Blocked: " + "; ".join(b["reason"] for b in blocked)
            if blocked
            else "No recorded block overlaps this period.",
        )
    else:
        checks.append(
            {
                "key": "booking_availability",
                "label": "Availability for an event period",
                "result": "UNVERIFIED",
                "message": "Enter event start and end to check bookings, blocks and operating hours.",
            }
        )
    unavailable = any(
        item["result"] == "UNMET"
        and item["key"]
        in {"operational_status", "operating_hours", "date_blocks", "approved_bookings"}
        for item in checks
    )
    return {
        "venue": venue,
        "criteria": checks,
        "matches_recorded_requirements": not any(item["result"] == "UNMET" for item in checks),
        "availability_status": (
            "UNAVAILABLE" if unavailable else "AVAILABLE" if has_period else "UNVERIFIED"
        ),
    }


def search_venues(criteria):
    venues = (
        Venue.objects.filter(in_service=True)
        .select_related("created_by", "updated_by")
        .prefetch_related("blocks", occupancy_prefetch())
    )
    if criteria.get("attendance") is not None:
        venues = venues.filter(capacity__gte=criteria["attendance"])
    labels = {}
    if criteria.get("layout"):
        venues = venues.supporting_layout(criteria["layout"])
        labels = label_map()
    return [
        match
        for venue in venues
        if (match := assess_venue(venue, criteria, labels))["matches_recorded_requirements"]
    ]


def ensure_shortlist_editable(event):
    if event.status in TERMINAL_STATUSES:
        raise ValidationError("Closed, cancelled or rejected events have read-only shortlists.")


def add_to_shortlist(event, venue, criteria, user):
    """The caller holds the event row lock, serialising add/remove operations."""
    ensure_shortlist_editable(event)
    existing = VenueShortlistEntry.objects.filter(event=event, venue=venue).first()
    if existing:
        return existing, False
    # Block writes lock this same venue row. Re-read it under that lock so an
    # intervening staff edit/block cannot bypass the final add-time assessment.
    venue = Venue.objects.select_for_update().get(pk=venue.pk)
    match = assess_venue(venue, criteria)
    if not match["matches_recorded_requirements"]:
        raise ValidationError(
            "This venue no longer matches the saved search. Run the search again."
        )
    entry = VenueShortlistEntry.objects.create(
        event=event, venue=venue, search_criteria=criteria, created_by=user
    )
    record(user, f"POST /api/events/{event.pk}/venue-shortlist/", allowed=True, obj=entry)
    return entry, True


def remove_from_shortlist(event, entry, user):
    ensure_shortlist_editable(event)
    record(
        user,
        f"DELETE /api/events/{event.pk}/venue-shortlist/{entry.venue_id}/",
        allowed=True,
        obj=entry,
    )
    entry.delete()
