"""
Celery app stub. No tasks are defined or run in M1 — the media pipeline
(M3), outcome/rollup recompute (M4/M5), and notifications (later) are the
first real consumers. Wired up now so `worker`/`beat` have a stable entry
point to point at once those milestones land.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("hevo_training")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
