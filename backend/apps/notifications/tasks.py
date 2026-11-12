"""Celery tasks: thin wrappers, as in `bot_sim.tasks`. The decisions and the idempotency live in
`sweeps` and `services`, driven by the database, so these are safe to run any time from anywhere."""

from __future__ import annotations

from celery import shared_task

from . import services, sweeps


@shared_task(name="notifications.sweep", ignore_result=True)
def sweep() -> dict[str, int]:
    """Deadline and review reminders (see `sweeps`)."""
    return sweeps.sweep()


@shared_task(name="notifications.prune", ignore_result=True)
def prune() -> int:
    """Delete old notifications (see `services.prune`)."""
    return services.prune()
