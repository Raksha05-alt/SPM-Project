"""SCRUM-66 - re-check approved venues when the event's requirements change.

Two layers, so the same assessment serves an applied edit and a preview:

* ``impact_of(event, proposed)`` is **read-only**. For each approved venue
  booking a change touches, it says which requirements the venue would no
  longer meet. SCRUM-78 (ASSESS) can call it with a change request's
  ``proposed_values`` to preview suitability without writing anything.
* ``record_reviews(event, impacts, actor)`` persists the outcome inside the
  action's transaction: it flags unsuitable bookings for review and notifies
  the coordinator (AC1/AC2), resolves a review a later change makes
  unnecessary, and raises nothing when suitability is unaffected (AC4).

Which bookings a change re-checks (AC5, SCRUM-87 contract):

* expected attendance and required layout belong to the **main programme**,
  so only main bookings are re-checked against them. A breakout keeps its own
  attendance and layout; an event-wide attendance change never touches it.
* accessibility needs apply to the whole event, so every approved booking is
  re-checked when they change.

Until SCRUM-87's sessions land on main, every booking belongs to the main
programme. ``is_main`` reads the session kind once it exists.

Accessibility needs are free text. The re-check treats newly stated needs as
requiring step-free access and flags a venue whose wheelchair access is not
recorded as available; a venue with confirmed access is not flagged, because
the text cannot be judged further.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils import timezone

from apps.events.models import ChangeSource, EventRequest, VenueReview

# Public SCRUM-70 provider contract; kept separate from suitability state.
from apps.events.period_conflicts import shifted, venue_conflicts  # noqa: F401, E402
from apps.notifications.models import NotificationKind, NotificationTarget
from apps.notifications.services import notify
from apps.venues.layouts import label_map
from apps.venues.models import BookingStatus, VenueBooking
from apps.venues.suitability import Reason, Requirement, Requirements, assess

ATTENDANCE = "expected_attendance"
LAYOUT = "required_layout"
ACCESSIBILITY = "accessibility_needs"
# AC4 - only these fields can change whether a booked venue suits the event.
RECHECK_FIELDS = (ATTENDANCE, LAYOUT, ACCESSIBILITY)
MAIN_ONLY_FIELDS = frozenset({ATTENDANCE, LAYOUT})


@dataclass
class BookingImpact:
    """One approved booking re-checked against the changed requirements."""

    booking: VenueBooking
    rechecked_for: list[str]
    reasons: list[Reason] = field(default_factory=list)

    @property
    def unsuitable(self) -> bool:
        return bool(self.reasons)

    def as_dict(self) -> dict:
        return {
            "booking": self.booking.pk,
            "venue": self.booking.venue.name,
            "rechecked_for": self.rechecked_for,
            "unsuitable": self.unsuitable,
            "reasons": [reason.as_dict() for reason in self.reasons],
        }


def is_main(booking) -> bool:
    """True for the main programme's booking (every booking before SCRUM-87)."""
    session = getattr(booking, "session", None)
    return session is None or getattr(session, "kind", "MAIN") == "MAIN"


def booking_attendance(booking, event_attendance):
    """AC5 - the attendance a booking is checked against.

    The main programme follows the event's (proposed) expected attendance; a
    breakout keeps its own booked attendance.
    """
    return event_attendance if is_main(booking) else booking.attendance


def _current(event: EventRequest, name: str):
    return getattr(event, name)


def _changed(event: EventRequest, proposed: dict) -> set[str]:
    return {
        name
        for name in RECHECK_FIELDS
        if name in proposed and proposed[name] != _current(event, name)
    }


def _needs_access(value) -> bool:
    return bool((value or "").strip())


def unsuitable(booking, requirements: Requirements, labels: dict | None = None) -> list[Reason]:
    """Every requirement the booked venue does not meet (SCRUM-71 rules)."""
    return assess(booking.venue, requirements, labels=labels).reasons


def _open_accessibility(booking) -> bool:
    review = booking.suitability_reviews.filter(resolved_at__isnull=True).first()
    return bool(
        review and any(r.get("requirement") == Requirement.ACCESSIBILITY for r in review.reasons)
    )


def impact_of(
    event: EventRequest,
    proposed: dict,
    *,
    changed: set[str] | None = None,
    labels: dict | None = None,
) -> list[BookingImpact]:
    """Read-only: re-check the approved bookings a change to ``proposed`` touches.

    ``proposed`` maps event field names to their new values (an edit's saved
    values, or a change request's ``proposed_values``). ``changed`` names the
    fields that changed; when omitted it is worked out against ``event``'s
    current values. Fields outside ``RECHECK_FIELDS`` never trigger a
    re-check (AC4). Writes nothing.
    """
    changed = set(_changed(event, proposed) if changed is None else changed) & set(RECHECK_FIELDS)
    if not changed:
        return []
    labels = label_map() if labels is None else labels
    values = {name: proposed.get(name, _current(event, name)) for name in RECHECK_FIELDS}
    impacts = []
    bookings = (
        VenueBooking.objects.filter(event=event, status=BookingStatus.APPROVED)
        .select_related("venue")
        .order_by("pk")
    )
    for booking in bookings:
        main = is_main(booking)
        relevant = sorted(changed if main else changed - MAIN_ONLY_FIELDS)
        if not relevant:
            continue  # AC5 - an attendance or layout change leaves a breakout alone.
        access_changed = ACCESSIBILITY in changed and _needs_access(values[ACCESSIBILITY])
        requirements = Requirements(
            attendance=booking_attendance(booking, values[ATTENDANCE]),
            layout=(values[LAYOUT] or booking.layout) if main else booking.layout,
            required_facilities=tuple(booking.required_facilities or ()),
            wheelchair_access_required=(
                booking.wheelchair_access_required
                or access_changed
                # Carry an existing flag through unrelated edits only.
                or (ACCESSIBILITY not in changed and _open_accessibility(booking))
            ),
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
        )
        impacts.append(
            BookingImpact(
                booking=booking,
                rechecked_for=relevant,
                reasons=unsuitable(booking, requirements, labels),
            )
        )
    return impacts


def _reason_dicts(impact: BookingImpact) -> list[dict]:
    return [reason.as_dict() for reason in impact.reasons]


def resolve_open(booking, *, actor, resolution: str, at=None) -> int:
    """Close the booking's open review, if any, keeping it on record."""
    return VenueReview.objects.filter(booking=booking, resolved_at__isnull=True).update(
        resolved_at=at or timezone.now(),
        resolved_by=actor,
        resolution=resolution,
    )


def record_reviews(
    event: EventRequest,
    impacts: list[BookingImpact],
    actor,
    *,
    source: str = ChangeSource.EVENT_EDIT,
) -> list[VenueReview]:
    """Persist the re-check outcome; call inside the action's transaction.

    * unsuitable, no open review: open one and notify the coordinator;
    * unsuitable with the same reasons already open: nothing new (a replay or
      a repeat save does not notify again);
    * unsuitable with different reasons: the open review is resolved as
      superseded and a new one is opened and notified;
    * suitable again: the open review is resolved; no notice is needed.

    Returns the reviews opened now.
    """
    opened = []
    now = timezone.now()
    for impact in impacts:
        booking = impact.booking
        current = (
            VenueReview.objects.select_for_update()
            .filter(booking=booking, resolved_at__isnull=True)
            .first()
        )
        if not impact.unsuitable:
            if current is not None:
                resolve_open(
                    booking,
                    actor=actor,
                    resolution="A later change means the venue suits the event again.",
                    at=now,
                )
            continue
        reasons = _reason_dicts(impact)
        if current is not None and current.reasons == reasons:
            continue
        if current is not None:
            resolve_open(booking, actor=actor, resolution="Replaced by a newer review.", at=now)
        review = VenueReview.objects.create(
            event=event,
            booking=booking,
            reasons=reasons,
            changed_fields=impact.rechecked_for,
            source=source,
            raised_by=actor,
            raised_at=now,
        )
        opened.append(review)
        details = " ".join(r["message"] for r in reasons)
        notify(
            event=event,
            kind=NotificationKind.VENUE_REVIEW,
            occurrence=f"venue-review:{review.pk}",
            recipients=[event.coordinator_id],
            target_type=NotificationTarget.VENUE_BOOKING,
            target_id=booking.pk,
            message=(
                f'{booking.venue.name} needs review for "{event.name}" after the event '
                f"changed: {details}"
            ),
        )
    return opened


def recheck_after_edit(event: EventRequest, changed: list[str], actor) -> list[VenueReview]:
    """The SCRUM-61 edit path's hook: re-check and record, in its transaction."""
    relevant = set(changed) & set(RECHECK_FIELDS)
    if not relevant:
        return []
    proposed = {name: _current(event, name) for name in RECHECK_FIELDS}
    return record_reviews(event, impact_of(event, proposed, changed=relevant), actor)


def open_reviews(event: EventRequest):
    """AC3 - unresolved reviews of the event's currently approved bookings."""
    return (
        VenueReview.objects.filter(
            event=event, resolved_at__isnull=True, booking__status=BookingStatus.APPROVED
        )
        .select_related("booking__venue", "raised_by")
        .order_by("booking_id")
    )


# --------------------------------------------------------------------------
# SCRUM-18 - tell registered attendees when a confirmed event changes
# --------------------------------------------------------------------------
#
# Published for DISRUPTION (SCRUM-86) and APPLY (SCRUM-80): after an action has
# changed a confirmed event's date, time or venue, it calls
# ``notify_attendees_of_change`` inside its own transaction. Cancellation
# (SCRUM-77's ``cancel_event``) calls ``notify_attendees_of_cancellation``.
# Only attendees currently Registered hear: withdrawn attendees and waiting-list
# entries do not (SCRUM-14/19). Messages carry public details only - never staff
# notes, decision reasons or Safety facts.

ATTENDEE_CHANGES = ("date", "time", "venue")


def registered_attendees(event: EventRequest) -> list[int]:
    """AC3/AC4 - ids of active attendees whose registration for ``event`` stands."""
    from apps.registrations.models import Registration, RegistrationStatus

    return list(
        Registration.objects.filter(
            event=event,
            status=RegistrationStatus.REGISTERED,
            attendee__is_active=True,
        )
        .order_by("attendee_id")
        .values_list("attendee_id", flat=True)
        .distinct()
    )


def _local(moment) -> str:
    return timezone.localtime(moment).strftime("%a %d %b %Y, %H:%M")


def _period(start, end) -> str:
    if start is None or end is None:
        return "date and time to be confirmed"
    local_end = timezone.localtime(end)
    same_day = timezone.localtime(start).date() == local_end.date()
    return (
        f"{_local(start)} to {local_end:%H:%M}" if same_day else f"{_local(start)} to {_local(end)}"
    )


def describe_for_attendees(event: EventRequest) -> str:
    """AC2 - the event's current public details, as an attendee may see them.

    Name, date and time (Singapore time) and each approved room with its
    session, location and period - the same public projection the confirmed
    arrangements and attendee views use.
    """
    from apps.events.confirmation import confirmed_venues

    lines = [f"When: {_period(event.preferred_start, event.preferred_end)} (Singapore time)."]
    venues = confirmed_venues(event)
    if not venues:
        lines.append("Where: venue to be confirmed.")
    for venue in venues:
        place = f"{venue['venue']}, {venue['location']}" if venue["location"] else venue["venue"]
        session = "" if len(venues) == 1 else f"{venue['session_name']}: "
        lines.append(f"Where: {session}{place} ({_period(venue['starts_at'], venue['ends_at'])}).")
    return " ".join(lines)


def _changed_phrase(changed) -> str:
    items = [c for c in ATTENDEE_CHANGES if c in changed]
    if not items or set(changed) - set(ATTENDEE_CHANGES):
        raise ValueError(f"Say which of {', '.join(ATTENDEE_CHANGES)} changed.")
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def notify_attendees_of_change(event: EventRequest, *, changed, occurrence: str):
    """AC1-AC4 - after a confirmed event's date, time or venue changed.

    ``changed`` names what changed (``date``, ``time``, ``venue``).
    ``occurrence`` must come from the persisted change that was applied - for
    example the change request or booking history row - so a replay never
    notifies twice. Call inside the applying action's transaction.
    """
    phrase = _changed_phrase(changed)
    return notify(
        event=event,
        kind=NotificationKind.EVENT_CHANGED,
        occurrence=occurrence,
        recipients=registered_attendees(event),
        message=(
            f'The {phrase} of "{event.name}", which you are registered for, changed. '
            f"Updated details: {describe_for_attendees(event)}"
        ),
    )


def notify_attendees_of_cancellation(event: EventRequest, *, occurrence: str):
    """AC5 - the event was cancelled; registered attendees are told once.

    The coordinator's cancellation reason is an internal note and is not shared.
    """
    when = _period(event.preferred_start, event.preferred_end)
    return notify(
        event=event,
        kind=NotificationKind.EVENT_CANCELLED,
        occurrence=occurrence,
        recipients=registered_attendees(event),
        message=(
            f'"{event.name}" ({when}), which you registered for, has been cancelled '
            "and will not take place."
        ),
    )
