"""Celery entry points. Thin on purpose: the work, and every decision about
duplicates and retries, lives in `services` and is driven by the database."""

from __future__ import annotations

import logging

from celery import shared_task
from celery.signals import worker_ready
from django.conf import settings

from . import services

log = logging.getLogger(__name__)

_LIMIT = settings.MEDIA_TRANSCODE_TIMEOUT_SECONDS


@shared_task(
    name="media_pipeline.transcode",
    ignore_result=True,
    soft_time_limit=_LIMIT + 600,
    time_limit=_LIMIT + 900,
)
def transcode_asset(asset_id: int) -> str:
    """Process one uploaded video. Harmless to run twice: the second run finds
    the asset already claimed or finished and does nothing."""
    return services.process_asset(asset_id)


@shared_task(name="media_pipeline.recover", ignore_result=True)
def recover() -> dict[str, int]:
    return services.recover_stuck_assets()


@worker_ready.connect
def _recover_on_start(sender=None, **kwargs) -> None:
    """A fresh worker first picks up what the last one (or a lost message) left."""
    try:
        counts = services.recover_stuck_assets()
        log.info("Media recovery on worker start: %s", counts)
    except Exception:  # never stop a worker from starting
        log.exception("Media recovery on worker start failed")
