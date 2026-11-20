from django.apps import AppConfig


class CertificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.certification"
    label = "certification"

    def ready(self) -> None:
        from . import signals  # noqa: F401
