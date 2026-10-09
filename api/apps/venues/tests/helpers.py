from apps.accounts.models import User
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


def booking_payload(event, venue, /, **overrides):
    data = {
        "event": event.pk,
        "venue": venue.pk,
        "start": iso(event.preferred_start),
        "end": iso(event.preferred_end),
        "attendance": 100,
        "layout": "THEATRE",
        "facilities": ["Projector"],
        "accessibility_needs": "",
        "notes": "",
    }
    data.update(overrides)
    return data


def make_user(email, role, **extra):
    return User.objects.create_user(
        username=email, email=email, password="pw-for-tests-only", role=role, **extra
    )
