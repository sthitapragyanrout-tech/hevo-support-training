from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bot_sim.models import SimSession, SimTurn


class Command(BaseCommand):
    help = "Delete the message text of old practice tickets, keeping scores and results."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=settings.SIMBOT_TRANSCRIPT_RETENTION_DAYS)
        old = SimSession.objects.filter(finished_at__lt=cutoff).exclude(
            turns__text="[removed after the retention period]"
        )
        ids = list(old.values_list("pk", flat=True))
        removed = SimTurn.objects.filter(session_id__in=ids).update(
            text="[removed after the retention period]"
        )
        SimSession.objects.filter(pk__in=ids).update(scenario_snapshot={})
        self.stdout.write(f"{removed} messages cleared in {len(ids)} sessions.")
