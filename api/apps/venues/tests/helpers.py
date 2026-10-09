from apps.venues.models import BookingStatus, VenueBlock, VenueBooking


def book(event, venue, start=None, end=None, status=BookingStatus.APPROVED, **extra):
    return VenueBooking.objects.create(
        event=event,
        venue=venue,
        start=start or event.preferred_start,
        end=end or event.preferred_end,
        attendance=extra.pop("attendance", 100),
        status=status,
        **extra,
    )


def block(venue, start, end, reason="Maintenance", by=None):
    return VenueBlock.objects.create(
        venue=venue, start=start, end=end, reason=reason, created_by=by
    )


def iso(moment):
    return moment.isoformat()
