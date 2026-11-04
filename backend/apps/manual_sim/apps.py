from django.apps import AppConfig


class ManualSimConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manual_sim"
    label = "manual_sim"

    def ready(self) -> None:
        from django.db.models.signals import post_delete

        from . import files
        from .models import SubmissionFile

        # A file never outlives the row that describes it.
        post_delete.connect(
            files.remove_after_delete,
            sender=SubmissionFile,
            dispatch_uid="manual_sim.remove_attachment",
        )
