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


# --------------------------------------------------------------------------
# SCRUM-59/78 - assess a change request before the coordinator decides it
# --------------------------------------------------------------------------
#
# ``assess_change`` composes the published providers into one read-only
# assessment: SCRUM-66 suitability (``impact_of``), SCRUM-70 proposed-period
# conflicts (``venue_conflicts``, buffered and hold-aware), SCRUM-12 equipment
# stock and SCRUM-21/81 registrations. It writes nothing - it never reserves,
# releases, approves or marks an arrangement reviewed - so the coordinator can
# open it as often as they like. Applying an approved change is SCRUM-80.

PERIOD_FIELDS = ("preferred_start", "preferred_end")
NO_IMPACT = "This change does not affect any existing arrangements."


def _typed(proposed: dict) -> dict:
    """Stored proposed values with datetimes back as aware datetimes."""
    from django.utils.dateparse import parse_datetime

    values = dict(proposed)
    for name in PERIOD_FIELDS:
        if isinstance(values.get(name), str):
            values[name] = parse_datetime(values[name])
    return values


def _period_change(event: EventRequest, proposed: dict):
    """The proposed (start, end) when the date or time changes, else None."""
    if not set(PERIOD_FIELDS) & set(proposed):
        return None
    start = proposed.get("preferred_start", event.preferred_start)
    end = proposed.get("preferred_end", event.preferred_end)
    if not (start and end and event.preferred_start and event.preferred_end):
        return None
    if (start, end) == (event.preferred_start, event.preferred_end):
        return None
    return start, end


def _venue_impacts(event, change, proposed, period) -> tuple[list[dict], list[str]]:
    from apps.venues.occupancy import conflict_references

    warnings = []
    rechecked = {item.booking.pk: item for item in impact_of(event, proposed)}
    moved_by_booking = {}
    if period is not None:
        try:
            found = venue_conflicts(event, proposed, target_bookings=change.target_bookings or None)
        except ValueError:
            # A booking named in the request is no longer approved: assess them all.
            warnings.append("A venue booking named in the request is no longer approved.")
            found = venue_conflicts(event, proposed)
        moved_by_booking = {row["booking"]: row for row in found}
    targeted = set(change.target_bookings)
    rows = []
    live = VenueBooking.objects.filter(event=event).occupying().select_related("venue", "session")
    for booking in live.order_by("pk"):
        moved = moved_by_booking.get(booking.pk)
        if booking.status == BookingStatus.HELD and period is not None:
            # A live hold occupies its slot too (SCRUM-88); SCRUM-70 covers approved ones.
            start, end = shifted(booking, event, proposed)
            moved = {
                "starts_at": start,
                "ends_at": end,
                "conflicts": conflict_references(
                    booking.venue, start, end, exclude_booking_id=booking.pk
                ),
            }
        recheck = rechecked.get(booking.pk)
        if moved is None and recheck is None and booking.pk not in targeted:
            continue
        reasons = [reason.message for reason in recheck.reasons] if recheck else []
        clashes = [
            {
                "booking": clash["id"],
                "event": clash["event_id"],
                "starts_at": clash["starts_at"],
                "ends_at": clash["ends_at"],
            }
            for clash in (moved or {}).get("conflicts", [])
        ]
        rows.append(
            {
                "booking": booking.pk,
                "venue": booking.venue.name,
                "session": booking.session.name,
                "status": booking.status,
                "status_label": booking.get_status_display(),
                "starts_at": booking.starts_at,
                "ends_at": booking.ends_at,
                "proposed_starts_at": moved["starts_at"] if moved else None,
                "proposed_ends_at": moved["ends_at"] if moved else None,
                "rechecked_for": recheck.rechecked_for if recheck else [],
                "unsuitable": bool(reasons),
                "unsuitable_reasons": reasons,
                "conflicts": clashes,
                "referenced": booking.pk in targeted,
            }
        )
        if reasons:
            warnings.append(
                f"{booking.venue.name} may no longer suit the event: {' '.join(reasons)}"
            )
        if clashes:
            warnings.append(
                f"{booking.venue.name} is already booked for another event at the proposed time."
            )
    return rows, warnings


def _equipment_impacts(event, change, proposed, period) -> tuple[list[dict], list[str]]:
    from apps.equipment.models import EquipmentRequest, EquipmentRequestStatus
    from apps.equipment.services import available_quantity

    warnings = []
    notes_changed = "equipment_notes" in proposed
    targeted = set(change.target_equipment_requests)
    requests = (
        EquipmentRequest.objects.filter(plan__event=event)
        .exclude(status=EquipmentRequestStatus.WITHDRAWN)
        .select_related("equipment_type")
        .order_by("pk")
    )
    rows = []
    for item in requests:
        reasons = []
        available = shortfall = None
        if period is not None:
            # Equipment uses the event's own period, without venue buffers.
            available = available_quantity(item.equipment_type, *period, exclude_event=event)
            shortfall = max(0, item.quantity - available)
            reasons.append("The date or time changes, so its period must be checked again.")
            if shortfall:
                warnings.append(
                    f"Only {available} {item.equipment_type.name} available at the proposed "
                    f"time; {item.quantity} needed ({shortfall} short)."
                )
        if notes_changed:
            reasons.append("The equipment requirements change.")
        if item.pk in targeted:
            reasons.append("The request names this equipment.")
        if not reasons:
            continue
        rows.append(
            {
                "request": item.pk,
                "equipment_type": item.equipment_type.name,
                "quantity": item.quantity,
                "status": item.status,
                "status_label": item.get_status_display(),
                "available_at_proposed_time": available,
                "shortfall": shortfall,
                "reasons": reasons,
            }
        )
    return rows, warnings


def _registration_impact(event, proposed, period) -> dict:
    from apps.registrations.services import capacity_of, waiting_list

    capacity = capacity_of(event)
    reasons = []
    if period is not None and capacity.registered:
        reasons.append(
            f"{capacity.registered} registered attendee(s) signed up for the current date and time."
        )
    attendance = proposed.get(ATTENDANCE)
    if isinstance(attendance, int) and attendance < capacity.registered:
        reasons.append(
            f"The proposed attendance of {attendance} is below the {capacity.registered} "
            "people already registered."
        )
    return {
        "registered": capacity.registered,
        "waitlisted": waiting_list(event).count(),
        "capacity": capacity.capacity,
        "affected": bool(reasons),
        "reasons": reasons,
    }


def assess_change(change, *, event: EventRequest | None = None) -> dict:
    """SCRUM-59 AC1 / SCRUM-78 AC1-AC4 - what a change request would affect. Read-only.

    Lists the venue bookings (approved, or held and not expired), equipment
    requests and registrations the proposed values may affect; flags a venue
    the change would make unsuitable, such as attendance above its capacity
    (AC2), and a clash with another booking at the proposed time (AC3); and
    says so plainly when nothing is affected (AC4). ``stale`` is True when the
    event has changed since the request was made.
    """
    from apps.events.change_requests import SIGNIFICANT_FIELDS, source_snapshot

    event = event or change.event
    proposed = _typed(change.proposed_values)
    period = _period_change(event, proposed)
    venues, venue_warnings = _venue_impacts(event, change, proposed, period)
    equipment, equipment_warnings = _equipment_impacts(event, change, proposed, period)
    registrations = _registration_impact(event, proposed, period)
    _, digest = source_snapshot(event)
    no_impact = not (venues or equipment or registrations["affected"])
    return {
        "change_request": change.pk,
        "significant": change.significant,
        "significant_fields": [name for name in SIGNIFICANT_FIELDS if name in proposed],
        "stale": digest != change.source_digest,
        "venue_bookings": venues,
        "equipment": equipment,
        "registrations": registrations,
        "warnings": venue_warnings + equipment_warnings + registrations["reasons"],
        "no_impact": no_impact,
        "summary": NO_IMPACT if no_impact else "Review the arrangements below before deciding.",
    }


# --------------------------------------------------------------------------
# SCRUM-80 - apply an approved change through staff review (gate APPLY)
# --------------------------------------------------------------------------
#
# ``apply_change`` starts the work: it lists every arrangement the approved
# change affects for staff review (AC1), supersedes the current Safety check
# and returns a Confirmed event to Planning (AC6). It moves nothing. Venue Staff
# and Technical Support then record, per arrangement, whether they can
# accommodate the change (AC2/AC3, ``review_arrangement``). Only when every
# arrangement is accommodated do the event's fields and its revised
# arrangements switch together, in one transaction, with before/after history
# and the change notices (AC4). If any cannot be accommodated, the originals
# stay; the coordinator may later record that the original arrangement is kept
# (``keep_original``) after agreeing it with the organiser.


class ApplyRefused(Exception):
    """An apply or review step that cannot happen now; nothing was saved."""

    def __init__(self, detail: str, status: int = 409, **extra):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.extra = extra


class NotArrangementStaff(Exception):
    """Venue Staff review venue bookings; Technical Support review equipment."""


def _iso(value):
    return value.isoformat() if value is not None else None


def _review_items(change, event, proposed) -> list[dict]:
    """AC1 - one review per affected venue booking and equipment request."""
    from apps.equipment.models import EquipmentRequest

    assessment = assess_change(change, event=event)
    attendance = proposed.get(ATTENDANCE)
    items = []
    for row in assessment["venue_bookings"]:
        booking = VenueBooking.objects.select_related("session").get(pk=row["booking"])
        starts = row["proposed_starts_at"] or booking.starts_at
        ends = row["proposed_ends_at"] or booking.ends_at
        new_attendance = (
            attendance if isinstance(attendance, int) and is_main(booking) else booking.attendance
        )
        reasons = list(row["unsuitable_reasons"])
        if row["conflicts"]:
            reasons.append("Another booking already holds the venue at the proposed time.")
        items.append(
            {
                "kind": "VENUE",
                "booking": booking,
                "before": {
                    "starts_at": _iso(booking.starts_at),
                    "ends_at": _iso(booking.ends_at),
                    "attendance": booking.attendance,
                },
                "proposed": {
                    "starts_at": _iso(starts),
                    "ends_at": _iso(ends),
                    "attendance": new_attendance,
                },
                "reasons": reasons,
            }
        )
    period = _period_change(event, proposed)
    for row in assessment["equipment"]:
        item = EquipmentRequest.objects.get(pk=row["request"])
        reservation = item.reservations.active().first()
        items.append(
            {
                "kind": "EQUIPMENT",
                "equipment_request": item,
                "before": {
                    "quantity": item.quantity,
                    "reserved": reservation is not None,
                    "starts_at": _iso(reservation.starts_at) if reservation else None,
                    "ends_at": _iso(reservation.ends_at) if reservation else None,
                },
                "proposed": {
                    "quantity": item.quantity,
                    "starts_at": _iso(period[0]) if period else None,
                    "ends_at": _iso(period[1]) if period else None,
                    "equipment_notes": proposed.get("equipment_notes"),
                },
                "reasons": list(row["reasons"]),
            }
        )
    return items


def _notify_staff(event, change, reviews, actor, *, kind, occurrence_prefix, message):
    from apps.accounts.models import Role, User

    for arrangement_kind, role, audience in (
        ("VENUE", Role.VENUE_STAFF, "venue"),
        ("EQUIPMENT", Role.TECHNICAL_SUPPORT, "technical"),
    ):
        if any(review.kind == arrangement_kind for review in reviews):
            notify(
                event=event,
                kind=kind,
                occurrence=f"{occurrence_prefix}:{change.pk}:{audience}",
                recipients=User.objects.filter(role=role, is_active=True),
                message=message,
                skip=actor,
            )


def apply_change(*, change, actor):
    """SCRUM-80 AC1/AC6 - start applying an approved change; returns ``(change, reviews)``.

    Locks the event, then the request. Refuses, with nothing saved, anyone but
    the assigned coordinator, a request that is not Approved, a finished event
    and a request whose event has changed since it was made. Records the
    SCRUM-70 period reviews and SCRUM-66 suitability reviews in this
    transaction, lists each affected arrangement for staff review, supersedes
    the Safety check and returns a Confirmed event to Planning. A change that
    affects no arrangement is applied at once.
    """
    from django.db import transaction

    from apps.core.audit import record
    from apps.core.statuses import EventStatus
    from apps.events.change_requests import (
        OPEN_TO_CHANGE_REQUESTS,
        NotAssignedCoordinator,
        StaleChangeRequest,
        source_snapshot,
    )
    from apps.events.models import ArrangementReview, ChangeRequestStatus, EventChangeRequest
    from apps.events.period_conflicts import record_period_reviews
    from apps.safety.services import arrangements_changed

    with transaction.atomic():
        event = EventRequest.objects.select_for_update().get(pk=change.event_id)
        locked = EventChangeRequest.objects.select_for_update().get(pk=change.pk)
        if event.coordinator_id is None or event.coordinator_id != actor.pk:
            raise NotAssignedCoordinator
        if locked.status != ChangeRequestStatus.APPROVED:
            raise ApplyRefused(
                f"Only an approved change can be applied; this one is {locked.get_status_display()}."
            )
        if event.status not in OPEN_TO_CHANGE_REQUESTS:
            raise ApplyRefused(f"A {event.get_status_display()} event cannot take a change.")
        if source_snapshot(event)[1] != locked.source_digest:
            raise StaleChangeRequest
        proposed = _typed(locked.proposed_values)
        items = _review_items(locked, event, proposed)
        if (
            locked.source_status == EventStatus.CONFIRMED
            and _period_change(event, proposed)
            and any(item["kind"] == "VENUE" for item in items)
        ):
            # SCRUM-70's real producer: persisted period assessments, originals kept.
            record_period_reviews(locked, actor)
        # SCRUM-66's real producer: flag venues the change makes unsuitable.
        record_reviews(event, impact_of(event, proposed), actor, source=ChangeSource.CHANGE_REQUEST)
        now = timezone.now()
        locked.applied_by = actor
        locked.applied_at = now
        reviews = [
            ArrangementReview.objects.create(change_request=locked, **item) for item in items
        ]
        record(
            actor, f"Change request {locked.pk} applied for staff review", allowed=True, obj=event
        )
        if not reviews:
            locked.save(update_fields=["applied_by", "applied_at", "updated_at"])
            _switch(event, locked, proposed, actor, [])
            locked.refresh_from_db()
            return locked, []
        locked.status = ChangeRequestStatus.IN_REVIEW
        locked.status_changed_at = now
        locked.save(
            update_fields=["status", "status_changed_at", "applied_by", "applied_at", "updated_at"]
        )
        # AC6 - the current Safety check no longer describes the arrangements.
        arrangements_changed(
            event, f"Approved change request {locked.pk} is under staff review.", actor
        )
        _notify_staff(
            event,
            locked,
            reviews,
            actor,
            kind=NotificationKind.CHANGE_REVIEW,
            occurrence_prefix="change-review",
            message=(
                f'An approved change to "{event.name}" needs your review: '
                f"{locked.description[:120]}"
                + ("…" if len(locked.description) > 120 else "")
                + " The current arrangement stays until every review is recorded."
            ),
        )
        return locked, reviews


def _still_possible(review, event, proposed) -> list[str]:
    """Why an accommodated arrangement can no longer take the change (fresh, under locks)."""
    from apps.equipment.contracts import lock_equipment_types
    from apps.equipment.services import available_quantity
    from apps.venues.models import Venue
    from apps.venues.occupancy import conflict_references

    def _dt(value):
        from django.utils.dateparse import parse_datetime

        return parse_datetime(value) if isinstance(value, str) else value

    problems = []
    if review.kind == "VENUE":
        booking = VenueBooking.objects.select_related("venue").get(pk=review.booking_id)
        Venue.objects.select_for_update().get(pk=booking.venue_id)
        if not VenueBooking.objects.filter(pk=booking.pk).occupying().exists():
            return [f"The booking for {booking.venue.name} is no longer approved or held."]
        start, end = _dt(review.proposed["starts_at"]), _dt(review.proposed["ends_at"])
        if conflict_references(booking.venue, start, end, exclude_booking_id=booking.pk):
            problems.append(f"{booking.venue.name} is already booked at the proposed time.")
        for impact in impact_of(event, proposed):
            if impact.booking.pk == booking.pk and impact.unsuitable:
                problems.extend(reason.message for reason in impact.reasons)
    else:
        item = review.equipment_request
        reservation = item.reservations.active().first()
        start, end = _dt(review.proposed.get("starts_at")), _dt(review.proposed.get("ends_at"))
        if reservation is not None and start and end:
            lock_equipment_types([item.equipment_type_id])
            available = available_quantity(item.equipment_type, start, end, exclude_event=event)
            if available < reservation.quantity:
                problems.append(
                    f"Only {available} {item.equipment_type.name} available at the proposed "
                    f"time; {reservation.quantity} reserved."
                )
    return problems


def review_arrangement(*, review, actor, outcome=None, reason=None):
    """SCRUM-80 AC2/AC3 - staff record whether they can accommodate one arrangement.

    Venue Staff review venue bookings; Technical Support review equipment. An
    accommodation is checked again under the locks (current conflicts,
    suitability and stock) and refused if it no longer fits. The outcome
    records who, when and why. The last accommodation switches the event and
    all its revised arrangements together (AC4); a "cannot accommodate" keeps
    the originals and tells the coordinator and organiser (AC3).
    Returns ``(review, change)``.
    """
    from django.db import transaction

    from apps.accounts.models import Role
    from apps.events.change_requests import ChangeDecisionError
    from apps.events.models import (
        ArrangementOutcome,
        ArrangementReview,
        ChangeRequestStatus,
        EventChangeRequest,
        VenuePeriodReview,
    )
    from apps.events.period_conflicts import review_period

    expected_role = {"VENUE": Role.VENUE_STAFF, "EQUIPMENT": Role.TECHNICAL_SUPPORT}
    with transaction.atomic():
        current = ArrangementReview.objects.select_related("change_request").get(pk=review.pk)
        event = EventRequest.objects.select_for_update().get(pk=current.change_request.event_id)
        change = EventChangeRequest.objects.select_for_update().get(pk=current.change_request_id)
        if not actor.is_active or actor.role != expected_role[current.kind]:
            raise NotArrangementStaff
        current = (
            # Lock the review row only: its booking or equipment line is an optional join.
            ArrangementReview.objects.select_for_update(of=("self",))
            .select_related("booking__venue", "equipment_request__equipment_type")
            .get(pk=review.pk)
        )
        if change.status != ChangeRequestStatus.IN_REVIEW:
            raise ApplyRefused("This change is no longer waiting for staff review.")
        from apps.core.statuses import EventStatus

        if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
            raise ApplyRefused(f"A {event.get_status_display()} event takes no further changes.")
        if current.outcome != ArrangementOutcome.PENDING:
            raise ApplyRefused(
                f"This arrangement is already {current.get_outcome_display().lower()}."
            )
        errors = {}
        if outcome not in (ArrangementOutcome.ACCOMMODATED, ArrangementOutcome.NOT_ACCOMMODATED):
            errors["outcome"] = "Choose whether the change can be accommodated."
        if not isinstance(reason, str) or not reason.strip():
            errors["reason"] = "Enter the reason for your outcome."
        if errors:
            raise ChangeDecisionError(errors)
        reason = reason.strip()
        proposed = _typed(change.proposed_values)
        if outcome == ArrangementOutcome.ACCOMMODATED:
            problems = _still_possible(current, event, proposed)
            if problems:
                raise ApplyRefused(
                    "The change can no longer be accommodated as proposed.", problems=problems
                )
        if current.kind == "VENUE":
            period_review = VenuePeriodReview.objects.filter(
                booking_id=current.booking_id,
                change_request=change,
                revision=change.revision,
                reviewed_at__isnull=True,
            ).first()
            if period_review is not None:
                # SCRUM-70's staff-outcome callback: a fresh, recorded period check.
                review_period(period_review, actor, reason=reason)
        current.outcome = outcome
        current.reviewed_by = actor
        current.reviewed_at = timezone.now()
        current.review_reason = reason
        current.save(update_fields=["outcome", "reviewed_by", "reviewed_at", "review_reason"])

        if outcome == ArrangementOutcome.NOT_ACCOMMODATED:
            notify(
                event=event,
                kind=NotificationKind.CHANGE_OUTCOME,
                occurrence=f"change-not-accommodated:{current.pk}",
                recipients=[event.coordinator_id, change.requested_by_id, event.created_by_id],
                message=(
                    f'Staff cannot accommodate the approved change to "{event.name}" for '
                    f"{_arrangement_name(current)}: {reason} The current arrangement stays in "
                    "place until you agree the next step."
                ),
                skip=actor,
            )
        elif not change.arrangement_reviews.exclude(
            outcome=ArrangementOutcome.ACCOMMODATED
        ).exists():
            _switch(event, change, proposed, actor, list(change.arrangement_reviews.all()))
        change.refresh_from_db()
        return current, change


def _arrangement_name(review) -> str:
    if review.kind == "VENUE":
        return f"the booking at {review.booking.venue.name}"
    return f"{review.equipment_request.equipment_type.name}"


def _attendee_changes(before: dict, event) -> list[str]:
    """Which of date, time and venue changed for registered attendees (SCRUM-18)."""
    old = (before.get("preferred_start"), before.get("preferred_end"))
    new = (event.preferred_start, event.preferred_end)
    if None in old or None in new or old == new:
        return []
    local = [timezone.localtime(moment) for moment in (*old, *new)]
    changed = []
    if (local[0].date(), local[1].date()) != (local[2].date(), local[3].date()):
        changed.append("date")
    if (local[0].time(), local[1].time()) != (local[2].time(), local[3].time()):
        changed.append("time")
    return changed


def _switch(event, change, proposed, actor, reviews) -> None:
    """SCRUM-80 AC4 - switch the event and its revised arrangements together.

    Rechecks, under the locks, that the event has not changed since the
    request and that every accommodated arrangement still fits. Then updates
    the event fields (SCRUM-60 history), each venue booking's period and
    attendance (booking history) and each equipment reservation's period
    (equipment history; technical approval goes back through Technical
    Support), supersedes the Safety check and sends the change notices.
    """
    from apps.equipment.models import (
        EquipmentHistory,
        EquipmentHistoryAction,
        EquipmentPlan,
    )
    from apps.equipment.reservations import advance_plan
    from apps.events.change_requests import StaleChangeRequest, source_snapshot
    from apps.events.history import record_field_changes
    from apps.events.models import ChangeRequestStatus
    from apps.events.services import snapshot_for_edit
    from apps.safety.services import arrangements_changed
    from apps.venues.models import VenueBookingHistory

    if source_snapshot(event)[1] != change.source_digest:
        raise StaleChangeRequest
    problems = [
        problem for review in reviews for problem in _still_possible(review, event, proposed)
    ]
    if problems:
        raise ApplyRefused(
            "The change can no longer be accommodated as proposed.", problems=problems
        )

    now = timezone.now()
    before = snapshot_for_edit(event)
    for name, value in proposed.items():
        setattr(event, name, value)
    event.updated_by = actor
    event.save()
    record_field_changes(
        event=event,
        before=before,
        after=snapshot_for_edit(event),
        actor=actor,
        source=ChangeSource.CHANGE_REQUEST,
        at=now,
    )
    note = f"Approved change request {change.pk} applied."
    equipment_changed = False
    for review in reviews:
        if review.kind == "VENUE":
            from django.utils.dateparse import parse_datetime

            booking = VenueBooking.objects.select_for_update().get(pk=review.booking_id)
            booking.starts_at = parse_datetime(review.proposed["starts_at"])
            booking.ends_at = parse_datetime(review.proposed["ends_at"])
            booking.attendance = review.proposed["attendance"]
            booking.save(update_fields=["starts_at", "ends_at", "attendance", "updated_at"])
            VenueBookingHistory.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=booking.status,
                actor=review.reviewed_by,
                reason=(
                    f"{note} Period {review.before['starts_at']} to {review.before['ends_at']} "
                    f"became {review.proposed['starts_at']} to {review.proposed['ends_at']}; "
                    f"attendance {review.before['attendance']} became "
                    f"{review.proposed['attendance']}."
                ),
                changed_at=now,
            )
            resolve_open(booking, actor=actor, resolution=f"{note} Venue Staff accommodated it.")
        else:
            item = review.equipment_request
            reservation = item.reservations.active().select_for_update().first()
            if reservation is not None and review.proposed.get("starts_at"):
                old = {
                    "starts_at": _iso(reservation.starts_at),
                    "ends_at": _iso(reservation.ends_at),
                }
                reservation.starts_at = event.preferred_start
                reservation.ends_at = event.preferred_end
                reservation.save(update_fields=["starts_at", "ends_at", "updated_at"])
                EquipmentHistory.objects.create(
                    plan=item.plan,
                    request=item,
                    reservation=reservation,
                    action=EquipmentHistoryAction.AMENDED,
                    plan_revision=item.plan.revision,
                    before=old,
                    after={
                        "starts_at": _iso(reservation.starts_at),
                        "ends_at": _iso(reservation.ends_at),
                    },
                    reason=note,
                    actor=review.reviewed_by,
                )
            equipment_changed = True
    if equipment_changed:
        plan = EquipmentPlan.objects.select_for_update().get(event=event)
        # Only the affected equipment goes back through Technical Support approval (AC6).
        advance_plan(plan, actor, note)

    change.status = ChangeRequestStatus.APPLIED
    change.status_changed_at = now
    change.completed_at = now
    change.completion_note = (
        "Every affected arrangement was accommodated."
        if reviews
        else ("The change affected no existing arrangement.")
    )
    change.save(
        update_fields=[
            "status",
            "status_changed_at",
            "completed_at",
            "completion_note",
            "updated_at",
        ]
    )
    arrangements_changed(event, note, actor)
    notify(
        event=event,
        kind=NotificationKind.CHANGE_OUTCOME,
        occurrence=f"change-applied:{change.pk}",
        recipients=[change.requested_by_id, event.created_by_id, event.coordinator_id],
        message=(
            f'The approved change to "{event.name}" has been applied: '
            f"{change.description[:120]}" + ("…" if len(change.description) > 120 else "")
        ),
        skip=actor,
    )
    _notify_staff(
        event,
        change,
        reviews,
        actor,
        kind=NotificationKind.CHANGE_OUTCOME,
        occurrence_prefix="change-applied",
        message=f'The revised arrangement for "{event.name}" is now in place.',
    )
    changed = _attendee_changes(before, event)
    if changed:
        notify_attendees_of_change(event, changed=changed, occurrence=f"change-applied:{change.pk}")


def keep_original(*, change, actor, reason=None):
    """SCRUM-80 AC3 - after agreeing it with the organiser, keep the original arrangement.

    Only the assigned coordinator, and only once staff have recorded that at
    least one arrangement cannot be accommodated. Nothing is applied: the
    event and its arrangements stay as they were. Open SCRUM-66 reviews raised
    by this change are resolved. The event stays in Planning so that it is
    checked and confirmed again.
    """
    from django.db import transaction

    from apps.events.change_requests import ChangeDecisionError, NotAssignedCoordinator
    from apps.events.models import ArrangementOutcome, ChangeRequestStatus, EventChangeRequest

    with transaction.atomic():
        event = EventRequest.objects.select_for_update().get(pk=change.event_id)
        locked = EventChangeRequest.objects.select_for_update().get(pk=change.pk)
        if event.coordinator_id is None or event.coordinator_id != actor.pk:
            raise NotAssignedCoordinator
        if locked.status != ChangeRequestStatus.IN_REVIEW:
            raise ApplyRefused("Only a change under staff review can be closed this way.")
        if not locked.arrangement_reviews.filter(
            outcome=ArrangementOutcome.NOT_ACCOMMODATED
        ).exists():
            raise ApplyRefused(
                "The original can be kept only after staff record that the change "
                "cannot be accommodated."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ChangeDecisionError({"reason": "Enter what was agreed with the organiser."})
        reason = reason.strip()
        now = timezone.now()
        for review in locked.arrangement_reviews.filter(kind="VENUE"):
            resolve_open(
                review.booking, actor=actor, resolution="The original arrangement was kept."
            )
        locked.status = ChangeRequestStatus.ORIGINAL_KEPT
        locked.status_changed_at = now
        locked.completed_at = now
        locked.completion_note = reason
        locked.save(
            update_fields=[
                "status",
                "status_changed_at",
                "completed_at",
                "completion_note",
                "updated_at",
            ]
        )
        notify(
            event=event,
            kind=NotificationKind.CHANGE_OUTCOME,
            occurrence=f"change-original-kept:{locked.pk}",
            recipients=[locked.requested_by_id, event.created_by_id],
            message=(
                f'The original arrangement for "{event.name}" is kept; the approved change '
                f"was not applied. {reason}"
            ),
            skip=actor,
        )
        return locked


def change_history(change) -> dict:
    """SCRUM-80 AC5 - the requested change, its decision, each arrangement outcome and who."""
    from apps.events.models import EventFieldChange

    def name(user):
        return None if user is None else (user.get_full_name() or user.email)

    reviews = change.arrangement_reviews.select_related(
        "booking__venue", "equipment_request__equipment_type", "reviewed_by"
    )
    fields = (
        EventFieldChange.objects.filter(
            event_id=change.event_id,
            source=ChangeSource.CHANGE_REQUEST,
            changed_at=change.completed_at,
        ).select_related("actor")
        if change.completed_at
        else []
    )
    return {
        "change_request": change.pk,
        "description": change.description,
        "reason": change.reason,
        "requested_by": name(change.requested_by),
        "requested_at": change.requested_at,
        "status": change.status,
        "status_label": change.get_status_display(),
        "decision": {
            "decided_by": name(change.decided_by),
            "decided_at": change.decided_at,
            "reason": change.decision_reason,
        },
        "applied_by": name(change.applied_by),
        "applied_at": change.applied_at,
        "completed_at": change.completed_at,
        "completion_note": change.completion_note,
        "arrangements": [
            {
                "id": review.pk,
                "kind": review.kind,
                "kind_label": review.get_kind_display(),
                "name": (
                    review.booking.venue.name
                    if review.kind == "VENUE"
                    else review.equipment_request.equipment_type.name
                ),
                "before": review.before,
                "proposed": review.proposed,
                "reasons": review.reasons,
                "outcome": review.outcome,
                "outcome_label": review.get_outcome_display(),
                "reviewed_by": name(review.reviewed_by),
                "reviewed_at": review.reviewed_at,
                "review_reason": review.review_reason,
            }
            for review in reviews
        ],
        "field_changes": [
            {
                "field": entry.field,
                "before": entry.before,
                "after": entry.after,
                "actor": name(entry.actor),
                "changed_at": entry.changed_at,
            }
            for entry in fields
        ],
    }
