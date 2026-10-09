from django.apps import AppConfig


class VenuesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.venues"
    label = "venues"

    def ready(self):
        from apps.events.services import CANCELLATION_HOOKS
        from apps.venues.bookings import release_for_cancelled_event

        # SCRUM-69 AC4 - a cancelled event stops holding its venues.
        if release_for_cancelled_event not in CANCELLATION_HOOKS:
            CANCELLATION_HOOKS.append(release_for_cancelled_event)
