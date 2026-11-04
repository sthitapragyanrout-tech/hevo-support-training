"""Celery entry points for practice tickets. They run only on the dedicated
simulation worker process (queue `sim`), never on the video worker or the web
process. All decisions about duplicates and retries live in `services`."""

from __future__ import annotations

import logging

from celery import shared_task
from celery.signals import worker_ready

from . import services

log = logging.getLogger(__name__)


@shared_task(name="bot_sim.process_turn", ignore_result=True, soft_time_limit=240, time_limit=300)
def process_turn(turn_id: int) -> str:
    """Evaluate one reply and answer it as the customer. Harmless to run twice."""
    return services.run_turn(turn_id)


@shared_task(name="bot_sim.finalize", ignore_result=True, soft_time_limit=240, time_limit=300)
def finalize_session(session_id: int) -> str:
    """Build the result for a finished conversation, once."""
    return services.finalize(session_id)


@shared_task(name="bot_sim.recover", ignore_result=True)
def recover() -> dict[str, int]:
    return services.recover()


@shared_task(
    name="bot_sim.generate_scenarios", ignore_result=True, soft_time_limit=900, time_limit=1000
)
def generate_scenarios(
    user_id: int, count: int, topic: str | None, persona: str | None
) -> dict[str, int]:
    """Draft new scenarios with the model; trainers approve them in the Console."""
    from django.contrib.auth import get_user_model

    from . import scenarios

    user = get_user_model().objects.filter(pk=user_id).first()
    return scenarios.generate_drafts(count, user=user, topic=topic, persona=persona)


@shared_task(
    name="bot_sim.import_scenarios", ignore_result=True, soft_time_limit=1500, time_limit=1600
)
def import_scenarios(run_id: int) -> str:
    """Import past customer queries as scenarios (see `importing`). Harmless to run twice."""
    from . import importing

    return importing.run_import(run_id)


@shared_task(name="bot_sim.top_up", ignore_result=True)
def top_up() -> str:
    """Nightly: queue an import when the approved-question bank is short (see `importing`)."""
    from . import importing

    return importing.top_up()


@worker_ready.connect
def _recover_on_start(sender=None, **kwargs) -> None:
    """A fresh simulation worker first picks up what the last one left half-done.
    (Only a worker consuming the `sim` queue does this, not the video worker.)"""
    try:
        queues = {q.name for q in getattr(sender, "app", None).amqp.queues.consume_from.values()}  # type: ignore[union-attr]
    except Exception:
        queues = set()
    if queues and "sim" not in queues:
        return
    try:
        log.info("Practice recovery on worker start: %s", services.recover())
    except Exception:  # never stop a worker from starting
        log.exception("Practice recovery on worker start failed")
