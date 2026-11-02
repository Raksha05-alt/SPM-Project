"""INT-03 / SCRUM-77: one confirmed cancellation releases actual resources."""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.audit import record
from apps.core.statuses import EventStatus
from apps.equipment.contracts import lock_equipment_types
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequest,
    EquipmentReservation,
    ReservationStatus,
)
from apps.equipment.releases import release_for_cancelled_event, release_reason
from apps.equipment.reservations import EquipmentActionDenied, EquipmentActionError
from apps.events.models import EventRequest
from apps.events.services import transition_event
from apps.notifications.models import Notification, NotificationKind
from apps.safety.services import arrangements_changed, current_check
from apps.venues.bookings import transition_booking
from apps.venues.models import BookingStatus, Venue

CANCELLABLE = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    }
)


def check_cancellation(event, actor):
    if (
        actor.role != Role.EVENT_COORDINATOR
        or event.coordinator_id != actor.pk
        or not actor.is_active
    ):
        raise EquipmentActionDenied("Only the assigned coordinator can cancel this event.")
    if event.status not in CANCELLABLE:
        raise EquipmentActionError("This event cannot be cancelled in its current status.")
    if event.preferred_end and event.preferred_end <= timezone.now():
        raise EquipmentActionError(
            "An event that has already taken place cannot release resources."
        )


def cancellation_preview(event, actor):
    check_cancellation(event, actor)
    bookings = list(
        event.venue_bookings.filter(status__in=[BookingStatus.PENDING, BookingStatus.APPROVED])
        .order_by("pk")
        .values("id", "venue_id", "venue__name", "status", "starts_at", "ends_at")
    )
    equipment = list(
        EquipmentReservation.objects.filter(
            request__plan__event=event, status=ReservationStatus.ACTIVE
        )
        .order_by("pk")
        .values(
            "id", "request_id", "request__equipment_type__name", "quantity", "starts_at", "ends_at"
        )
    )
    plan = EquipmentPlan.objects.filter(event=event).first()
    snapshot = {
        "id": event.pk,
        "status": event.status,
        "coordinator": event.coordinator_id,
        "assignment_revision": event.assignment_revision,
        "start": event.preferred_start,
        "end": event.preferred_end,
        "equipment_revision": plan.revision if plan else None,
        "venues": bookings,
        "equipment": equipment,
    }
    version = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "event": event.pk,
        "event_name": event.name,
        "version": version,
        "venue_bookings": bookings,
        "equipment_reservations": equipment,
    }


@transaction.atomic
def cancel_event(*, event, actor, expected_version, confirm_cancel=False, reason=""):
    event = EventRequest.objects.select_for_update().get(pk=event.pk)
    check_cancellation(event, actor)
    if confirm_cancel is not True:
        raise EquipmentActionError(
            "Confirm cancellation and resource release to continue.", status=400
        )
    reason = release_reason(reason)
    # Keep event -> venues (ID order) -> equipment types -> resource rows.
    venue_ids = event.venue_bookings.filter(
        status__in=[BookingStatus.PENDING, BookingStatus.APPROVED]
    ).values_list("venue_id", flat=True)
    list(Venue.objects.select_for_update().filter(pk__in=venue_ids).order_by("pk"))
    type_ids = EquipmentRequest.objects.filter(plan__event=event).values_list(
        "equipment_type_id", flat=True
    )
    lock_equipment_types(type_ids)
    snapshot = cancellation_preview(event, actor)
    if expected_version != snapshot["version"]:
        raise EquipmentActionError(
            "The event or its arrangements changed. Reload the cancellation summary."
        )
    check = current_check(event)
    # Mark Cancelled first within this transaction, so invalidation does not
    # create a misleading return-to-Planning transition or notification.
    transition_event(event, EventStatus.CANCELLED, actor)
    bookings = list(
        event.venue_bookings.select_for_update()
        .filter(status__in=[BookingStatus.PENDING, BookingStatus.APPROVED])
        .order_by("pk")
    )
    for booking in bookings:
        transition_booking(booking, BookingStatus.WITHDRAWN, actor, reason)
    released = release_for_cancelled_event(event=event, actor=actor, reason=reason)
    arrangements_changed(event, f"Event cancelled: {reason}", actor)
    recipients = {p.pk: p for p in (event.coordinator, event.created_by) if p}
    roles = []
    if bookings:
        roles.append(Role.VENUE_STAFF)
    if snapshot["equipment_reservations"] or EquipmentPlan.objects.filter(event=event).exists():
        roles.append(Role.TECHNICAL_SUPPORT)
    if check:
        roles.append(Role.SAFETY_OFFICER)
    recipients.update({p.pk: p for p in User.objects.filter(role__in=roles, is_active=True)})
    notify_cancellation(event, recipients, reason)
    record(actor, f"POST /api/events/{event.pk}/cancel/", allowed=True, obj=event, detail=reason)
    return {
        "event": event.pk,
        "status": event.status,
        "released_equipment_reservations": released,
        "withdrawn_venue_bookings": len(bookings),
    }


def notify_cancellation(event, recipients, reason):
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=person,
                event=event,
                kind=NotificationKind.EVENT_CANCELLED,
                message=f'"{event.name}" was cancelled. Its venue bookings were withdrawn and equipment reservations released. Reason: {reason}',
            )
            for person in recipients.values()
        ]
    )
