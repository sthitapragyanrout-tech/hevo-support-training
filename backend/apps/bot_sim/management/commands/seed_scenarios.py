from django.core.management.base import BaseCommand

from apps.bot_sim.models import Scenario
from apps.bot_sim.seed_data import SAMPLE_SCENARIOS


class Command(BaseCommand):
    help = "Create the hand-written sample practice scenarios, already approved (development)."

    def handle(self, *args, **options):
        made = 0
        for data in SAMPLE_SCENARIOS:
            _, created = Scenario.objects.get_or_create(
                issue_summary=data["issue_summary"],
                defaults={
                    **data,
                    "status": Scenario.Status.APPROVED,
                    "source": Scenario.Source.SEED,
                },
            )
            made += created
        self.stdout.write(
            f"{made} sample scenarios created ({len(SAMPLE_SCENARIOS) - made} already there)."
        )
