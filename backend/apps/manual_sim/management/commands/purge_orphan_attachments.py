"""Remove attachment files that no submission refers to (a crash between writing a file and
saving its row, or a leftover partial upload). Files younger than the grace period are left
alone, since an upload may be in flight. Safe to run any time; `--dry-run` only reports."""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.manual_sim import files
from apps.manual_sim.models import SubmissionFile
from apps.media_pipeline import services as media


class Command(BaseCommand):
    help = "Delete stored attachments that no submission refers to."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only list what would go.")

    def handle(self, *args, **options):
        folder = media.media_root() / files.FOLDER
        if not folder.is_dir():
            self.stdout.write("No attachments folder yet.")
            return
        grace = settings.MEDIA_DEBRIS_MIN_AGE_SECONDS
        known = {f"{u}.{e}" for u, e in SubmissionFile.objects.values_list("uuid", "extension")}
        now = time.time()
        removed = kept = 0
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name in known:
                continue
            if now - path.stat().st_mtime < grace:
                kept += 1
                continue
            self.stdout.write(f"{'Would remove' if options['dry_run'] else 'Removing'} {path.name}")
            if not options["dry_run"]:
                files.discard_paths(path)
            removed += 1
        self.stdout.write(self.style.SUCCESS(f"{removed} orphan file(s); {kept} too new to touch."))
