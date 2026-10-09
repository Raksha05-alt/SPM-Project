from django.apps import AppConfig


class EquipmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.equipment"
    label = "equipment"

    def ready(self):
        from apps.equipment.services import release_for_cancelled_event
        from apps.events.services import CANCELLATION_HOOKS

        if release_for_cancelled_event not in CANCELLATION_HOOKS:
            CANCELLATION_HOOKS.append(release_for_cancelled_event)
