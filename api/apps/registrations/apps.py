from django.apps import AppConfig


class RegistrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.registrations"
    label = "registrations"

    def ready(self):
        from apps.events.services import CANCELLATION_HOOKS
        from apps.registrations.services import notify_cancelled

        if notify_cancelled not in CANCELLATION_HOOKS:
            CANCELLATION_HOOKS.append(notify_cancelled)
