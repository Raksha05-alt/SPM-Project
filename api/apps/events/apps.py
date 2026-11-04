from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    label = "events"

    def ready(self):
        from apps.events import signals  # noqa: F401 - registers SCRUM-66 receivers
