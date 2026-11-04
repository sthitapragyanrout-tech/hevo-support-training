from django.core.management.base import BaseCommand

from apps.bot_sim.models import Scenario


class Command(BaseCommand):
    help = (
        "Forget which Zendesk ticket each imported scenario came from (the link back to the "
        "customer's ticket). The rewritten questions stay."
    )

    def handle(self, *args, **options):
        n = Scenario.objects.exclude(source_ticket_id=None).update(source_ticket_id=None)
        self.stdout.write(f"Removed the ticket link from {n} scenarios.")
