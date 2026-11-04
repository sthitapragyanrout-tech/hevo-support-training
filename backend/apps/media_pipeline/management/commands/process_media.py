from django.core.management.base import BaseCommand, CommandError

from apps.media_pipeline import services


class Command(BaseCommand):
    help = "Queue, process or recover uploaded videos."

    def add_arguments(self, parser):
        parser.add_argument("--enqueue", type=int, metavar="ID", help="Queue one asset.")
        parser.add_argument("--process", type=int, metavar="ID", help="Process one asset now.")
        parser.add_argument("--recover", action="store_true", help="Run the recovery sweeper.")

    def handle(self, *args, **options):
        if options["enqueue"] is not None:
            sent = services.enqueue(options["enqueue"])
            self.stdout.write("queued" if sent else "not queued")
        elif options["process"] is not None:
            self.stdout.write(services.process_asset(options["process"]))
        elif options["recover"]:
            self.stdout.write(str(services.recover_stuck_assets()))
        else:
            raise CommandError("Choose --enqueue ID, --process ID or --recover.")
