"""Practice work and video work run in separate processes: a stuck model call can't
starve ffmpeg, and a stuck conversion can't starve practice tickets. Queue names
alone aren't isolation, so this checks the process configuration as well."""

import re
from pathlib import Path

import pytest

from config.celery import app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tasks():
    app.loader.import_default_modules()
    return sorted(name for name in app.tasks if not name.startswith("celery."))


def queue_of(name: str) -> str:
    return app.amqp.router.route({}, name)["queue"].name


def test_every_task_goes_to_its_own_queue(tasks):
    sim = [t for t in tasks if t.startswith("bot_sim.")]
    media = [t for t in tasks if t.startswith("media_pipeline.")]
    assert sim and media
    assert {queue_of(t) for t in sim} == {"sim"}
    assert {queue_of(t) for t in media} == {"media"}
    assert set(tasks) == set(sim) | set(media)  # nothing falls through to a default queue


def test_the_scheduled_sweepers_use_the_right_queues():
    from django.conf import settings

    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        task = entry["task"]
        assert queue_of(task) == ("sim" if task.startswith("bot_sim.") else "media"), task


def worker_commands(text: str) -> dict[str, str]:
    """{'media': '<command>', 'sim': '<command>'} for each `celery … worker -Q <queue>`."""
    found = {}
    for line in text.splitlines():
        m = re.search(r"celery -A config worker\b.*?-Q (\w+)", line)
        if m:
            found[m.group(1)] = line
    return found


@pytest.mark.parametrize("path", ["Makefile", "docker-compose.yml"])
def test_each_queue_has_its_own_worker_process(path):
    text = (ROOT / path).read_text()
    commands = worker_commands(text)
    assert set(commands) == {"media", "sim"}, path
    for queue, other in (("media", "sim"), ("sim", "media")):
        # a worker consumes exactly one of the queues
        assert f"-Q {other}" not in commands[queue], (path, queue)
        assert "," not in re.search(r"-Q (\S+)", commands[queue]).group(1), (path, queue)


def test_compose_runs_them_as_distinct_services_and_a_single_scheduler():
    text = (ROOT / "docker-compose.yml").read_text()
    for service in ("worker-media", "worker-sim", "beat"):
        assert re.search(rf"^  {service}:", text, re.M), service
    assert len(re.findall(r"celery -A config beat", text)) == 1
    # the web process makes no model calls: it is not given a worker command
    web = text.split("  web:")[1].split("\n  worker-media:")[0]
    assert "celery" not in web


def test_the_web_process_never_builds_a_model_client():
    """Model clients are built by workers (`services._client`), never in a view."""
    views = (Path(__file__).resolve().parents[1] / "apps/bot_sim/views.py").read_text()
    console = (Path(__file__).resolve().parents[1] / "apps/bot_sim/console.py").read_text()
    for text in (views, console):
        assert "build_client" not in text and "OpenAIClient" not in text
