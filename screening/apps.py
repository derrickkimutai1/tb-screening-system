from django.apps import AppConfig


class ScreeningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "screening"

    def ready(self):
        # Importing for the side effect of registering the signal handlers.
        from . import signals  # noqa: F401
