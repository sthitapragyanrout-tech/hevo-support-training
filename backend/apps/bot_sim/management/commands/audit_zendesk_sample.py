from django.core.management.base import BaseCommand, CommandError

from apps.bot_sim import importing, zendesk


class Command(BaseCommand):
    help = (
        "Read a sample of past Zendesk tickets and report how many are genuine customer "
        "messages and why the rest are not. Reads Zendesk only: nothing goes to the model and "
        "no message text is kept — just counts and ticket ids. Must run before any import."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=40)

    def handle(self, *args, **options):
        if not zendesk.configured():
            raise CommandError(
                "Zendesk isn't connected: set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL "
                "and ZENDESK_API_TOKEN."
            )
        try:
            summary = importing.run_audit(options["count"])
        except zendesk.ZendeskError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Examined {summary.examined} tickets; {summary.accepted} look genuine.")
        for reason, n in summary.reasons.most_common():
            ids = ", ".join(str(i) for i in summary.rejected_ids[reason][:8])
            self.stdout.write(f"  {n:>3} rejected: {reason}   (e.g. tickets {ids})")
        if summary.accepted_ids:
            sample = ", ".join(str(i) for i in summary.accepted_ids[:8])
            self.stdout.write(f"Accepted, e.g. tickets {sample}")
            self.stdout.write(
                "Open a few of these in Zendesk and check each is a customer's own message."
            )
