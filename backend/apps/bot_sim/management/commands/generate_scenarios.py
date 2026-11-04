import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bot_sim import llm, scenarios
from simbot_engine.scenario import PERSONA_TYPES, TOPIC_POOL, Sample


class Command(BaseCommand):
    help = (
        "Ask the model for draft practice scenarios (trainers approve them in the Console). "
        "--from-file takes a JSONL export of past tickets ({subject, first_message}) for tone; "
        "personal data is scrubbed before the model sees it."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5)
        parser.add_argument("--topic", choices=sorted(TOPIC_POOL))
        parser.add_argument("--persona", choices=list(PERSONA_TYPES))
        parser.add_argument("--from-file", type=Path)

    def handle(self, *args, **opts):
        if not llm.configured():
            raise CommandError(llm.NOT_CONFIGURED)
        samples: list[Sample] = []
        if opts["from_file"]:
            for line in opts["from_file"].read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    samples.append(Sample(row.get("subject", ""), row.get("first_message", "")))
        result = scenarios.generate_drafts(
            opts["count"], topic=opts["topic"], persona=opts["persona"], samples=samples[:8]
        )
        self.stdout.write(str(result))
