from django.core.management.base import BaseCommand, CommandError

from apps.bot_sim import importing
from apps.bot_sim.errors import SimError
from apps.bot_sim.models import ScenarioImport


class Command(BaseCommand):
    help = (
        "Import past customer queries from Zendesk as practice scenarios (runs here, not on "
        "the worker). Refused until the data-protection sign-off is recorded and the sample "
        "audit has run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10)
        parser.add_argument("--topic", default=None)

    def handle(self, *args, **options):
        try:
            run = importing.create_run(None, options["count"], options["topic"])
        except SimError as exc:
            raise CommandError(exc.message) from exc
        importing.run_import(run.pk)
        run = ScenarioImport.objects.get(pk=run.pk)
        self.stdout.write(
            f"Import #{run.pk} {run.get_state_display().lower()}: examined {run.examined}, "
            f"approved {run.approved}, drafts {run.drafted}, duplicates {run.duplicates}, "
            f"failed {run.failed}."
        )
        for reason, n in sorted(run.rejected.items()):
            self.stdout.write(f"  {n:>3} not used: {reason}")
        if run.error:
            self.stdout.write(self.style.WARNING(run.error))
