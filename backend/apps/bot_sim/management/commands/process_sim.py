from django.core.management.base import BaseCommand, CommandError

from apps.bot_sim import services


class Command(BaseCommand):
    help = "Queue practice-ticket work or run the recovery sweeper."

    def add_arguments(self, parser):
        parser.add_argument("--enqueue-turn", type=int, metavar="TURN_ID")
        parser.add_argument("--enqueue-finalize", type=int, metavar="SESSION_ID")
        parser.add_argument("--recover", action="store_true")

    def handle(self, *args, **options):
        if options["enqueue_turn"] is not None:
            sent = services.enqueue_turn(options["enqueue_turn"])
            self.stdout.write("queued" if sent else "not queued")
        elif options["enqueue_finalize"] is not None:
            sent = services.enqueue_finalize(options["enqueue_finalize"])
            self.stdout.write("queued" if sent else "not queued")
        elif options["recover"]:
            self.stdout.write(str(services.recover()))
        else:
            raise CommandError("Choose --enqueue-turn, --enqueue-finalize or --recover.")
