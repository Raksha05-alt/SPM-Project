"""SCRUM-66 - close a venue review once its booking is no longer approved.

Listening to booking history keeps this out of the booking actions themselves:
every status change writes one VenueBookingHistory row in the action's
transaction, so the review closes (or rolls back) with it.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.venues.models import BookingStatus, VenueBookingHistory


@receiver(post_save, sender=VenueBookingHistory, dispatch_uid="scrum66_close_venue_review")
def close_review_when_booking_leaves_approved(sender, instance, created, **kwargs):
    # Approved only ever moves to another status, so this is a real departure.
    if not created or instance.from_status != BookingStatus.APPROVED:
        return
    from apps.events.impact import resolve_open

    resolve_open(
        instance.booking,
        actor=instance.actor,
        resolution=f"The booking was {instance.get_to_status_display().lower()}.",
        at=instance.changed_at,
    )
