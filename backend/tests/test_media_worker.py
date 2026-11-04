"""The real thing: an actual Celery worker process on the filesystem broker,
an actual ffmpeg, a shared database. These are the tests that prove restarts,
kills, duplicate messages and lost messages end up with one finished video and
no debris.

They need a database a second process can reach, so they run only against
Postgres (set DATABASE_URL), and need ffmpeg. Otherwise they skip, saying why.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.utils import timezone

from apps.accounts.models import Role
from apps.media_pipeline import services
from apps.media_pipeline.models import MediaAsset
from tests.media_helpers import HAVE_FFMPEG

BACKEND = Path(__file__).resolve().parent.parent

pytestmark = [
    pytest.mark.worker,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe are not installed"),
]

WRAPPER = """#!/bin/sh
# Stands in for ffmpeg so a test can slow down, fail, or count the transcodes.
case "$*" in
  *libx264*)
    echo "transcode $$" >> "$FAKE_LOG"
    if [ -f "$FAKE_FAIL" ]; then echo "No space left on device" >&2; exit 1; fi
    if [ -f "$FAKE_SLOW" ]; then
      echo $$ > "$FAKE_MARK"
      sleep "$(cat "$FAKE_SLOW")"
    fi
    ;;
esac
exec "$REAL_FFMPEG" "$@"
"""


@pytest.fixture(autouse=True)
def _need_postgres():
    if "postgresql" not in connection.settings_dict["ENGINE"]:
        pytest.skip("real-worker tests need Postgres (set DATABASE_URL); SQLite can't be shared")


@pytest.fixture
def rig(tmp_path, media_dirs, settings, monkeypatch):
    """Everything a worker subprocess shares with this test."""
    db = connection.settings_dict
    wrapper = tmp_path / "ffmpeg-wrapper"
    wrapper.write_text(WRAPPER)
    wrapper.chmod(0o755)
    broker = Path(settings.CELERY_BROKER_FOLDER)
    flags = {name: tmp_path / name for name in ("slow", "fail", "mark", "log")}
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_URL": (
            f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or 'localhost'}"
            f":{db['PORT'] or 5432}/{db['NAME']}"
        ),
        "MEDIA_ROOT": str(media_dirs),
        "CELERY_BROKER_FOLDER": str(broker),
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "MEDIA_MIN_FREE_MB": "1",
        "MEDIA_TRANSCODE_TIMEOUT_SECONDS": "8",
        "MEDIA_LEASE_SLACK_SECONDS": "1",
        "MEDIA_DEBRIS_MIN_AGE_SECONDS": "0",
        "MEDIA_RETRY_BACKOFF_SECONDS": "0",
        "MEDIA_REQUEUE_AFTER_SECONDS": "0",
        "FFMPEG_BIN": str(wrapper),
        "REAL_FFMPEG": shutil.which("ffmpeg") or "ffmpeg",
        "FAKE_LOG": str(flags["log"]),
        "FAKE_FAIL": str(flags["fail"]),
        "FAKE_SLOW": str(flags["slow"]),
        "FAKE_MARK": str(flags["mark"]),
    }
    # The test process must not run tasks itself or send to the broker; the
    # worker does the work, the CLI below does the queueing.
    monkeypatch.setattr(services, "enqueue", lambda *a, **k: True)
    rig = Rig(env=env, tmp=tmp_path, media=media_dirs, broker=broker, flags=flags)
    yield rig
    rig.stop_all()


class Rig:
    def __init__(self, env, tmp, media, broker, flags):
        self.env, self.tmp, self.media, self.broker, self.flags = env, tmp, media, broker, flags
        self.workers: list[subprocess.Popen] = []
        self.logs: list[Path] = []

    # -- processes ---------------------------------------------------------
    def start_worker(self) -> subprocess.Popen:
        log = self.tmp / f"worker-{len(self.workers)}.log"
        handle = open(log, "wb")
        process = subprocess.Popen(
            [sys.executable, "-m", "celery", "-A", "config", "worker", "-P", "solo",
             "-Q", "media", "-c", "1", "-l", "info",
             "--without-gossip", "--without-mingle", "--without-heartbeat"],
            cwd=BACKEND, env=self.env, stdout=handle, stderr=subprocess.STDOUT,
        )  # fmt: skip
        self.workers.append(process)
        self.logs.append(log)
        deadline = time.time() + 40
        while time.time() < deadline:
            if b" ready." in log.read_bytes():
                return process
            if process.poll() is not None:
                break
            time.sleep(0.2)
        pytest.fail(f"worker did not start:\n{log.read_text()[-2000:]}")

    def stop_all(self):
        for process in self.workers:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    def manage(self, *args, env=None):
        done = subprocess.run(
            [sys.executable, "manage.py", "process_media", *args],
            cwd=BACKEND, env=env or self.env, capture_output=True, text=True, timeout=60,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr[-2000:]
        return done.stdout.strip()

    def enqueue(self, asset_id: int) -> str:
        return self.manage("--enqueue", str(asset_id))

    # -- observations ------------------------------------------------------
    def wait_for(self, asset_id: int, status: str, timeout: float = 60) -> MediaAsset:
        deadline = time.time() + timeout
        while time.time() < deadline:
            asset = MediaAsset.objects.get(pk=asset_id)
            if asset.status == status:
                return asset
            time.sleep(0.25)
        tails = "\n---\n".join(log.read_text()[-1500:] for log in self.logs)
        pytest.fail(
            f"asset {asset_id} never reached {status!r} (is {asset.status!r}, "
            f"attempts={asset.attempts}, error={asset.error!r})\n{tails}"
        )

    def wait_for_file(self, path: Path, timeout: float = 30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return
            time.sleep(0.1)
        pytest.fail(f"{path.name} never appeared")

    def transcodes(self) -> int:
        log = self.flags["log"]
        return len(log.read_text().splitlines()) if log.exists() else 0

    def leftovers(self) -> list[str]:
        tmp = self.media / "tmp"
        return sorted(p.name for p in tmp.iterdir()) if tmp.exists() else []


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER)


def new_asset(author, clip) -> MediaAsset:
    return services.create_asset(SimpleUploadedFile("clip.mp4", clip.read_bytes()), author)


class TestRealWorker:
    def test_an_upload_becomes_a_ready_video(self, rig, author, sample_clip):
        asset = new_asset(author, sample_clip)
        original = rig.media / asset.original_path
        rig.start_worker()
        # A message for an asset that doesn't exist must not hurt the worker.
        rig.enqueue(987654)
        assert rig.enqueue(asset.pk) == "queued"
        ready = rig.wait_for(asset.pk, "ready")
        assert (rig.media / ready.video_path).is_file()
        assert (rig.media / ready.poster_path).is_file()
        assert not original.exists() and ready.original_purged
        assert rig.transcodes() == 1 and rig.leftovers() == []

    def test_the_same_message_delivered_twice_transcodes_once(self, rig, author, sample_clip):
        asset = new_asset(author, sample_clip)
        rig.flags["slow"].write_text("1")  # a moment's overlap between the two deliveries
        rig.enqueue(asset.pk)
        rig.enqueue(asset.pk)
        rig.start_worker()
        ready = rig.wait_for(asset.pk, "ready")
        time.sleep(1.5)  # let the duplicate be consumed too
        assert rig.transcodes() == 1
        assert ready.attempts == 1
        assert rig.leftovers() == []

    def test_a_killed_worker_is_recovered_by_the_next_one(self, rig, author, sample_clip):
        asset = new_asset(author, sample_clip)
        rig.flags["slow"].write_text("6")
        first = rig.start_worker()
        rig.enqueue(asset.pk)
        rig.wait_for_file(rig.flags["mark"])  # ffmpeg has started: it is mid-transcode
        zombie = int(rig.flags["mark"].read_text())

        first.send_signal(signal.SIGKILL)  # no goodbye: nothing is cleaned up
        first.wait(timeout=10)
        stuck = MediaAsset.objects.get(pk=asset.pk)
        assert stuck.status == MediaAsset.Status.PROCESSING and stuck.attempts == 1
        original = rig.media / stuck.original_path
        assert original.is_file(), "the original must survive a killed worker"

        # The new attempt is quick; the lease from the dead worker must run out first.
        rig.flags["slow"].unlink()
        time.sleep(max((stuck.lease_expires_at - timezone.now()).total_seconds(), 0) + 1)
        rig.start_worker()  # recovers on start: releases the lease, re-queues, processes
        ready = rig.wait_for(asset.pk, "ready")

        assert ready.attempts == 2
        assert (rig.media / ready.video_path).is_file()
        assert not original.exists() and ready.original_purged
        # Two attempts began (the killed one and the real one) but only one
        # produced a published file.
        assert rig.transcodes() == 2
        assert sorted(p.name for p in (rig.media / "videos").iterdir()) == [f"{ready.uuid}.mp4"]

        # The killed attempt's orphaned encoder was still running; once it
        # finishes, the debris it leaves is cleared by the sweeper.
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                os.kill(zombie, 0)
            except ProcessLookupError:
                break
            time.sleep(0.3)
        time.sleep(1)
        rig.manage("--recover")
        assert rig.leftovers() == []

    def test_a_polite_shutdown_lets_the_current_video_finish(self, rig, author, sample_clip):
        asset = new_asset(author, sample_clip)
        rig.flags["slow"].write_text("3")
        worker = rig.start_worker()
        rig.enqueue(asset.pk)
        rig.wait_for_file(rig.flags["mark"])
        worker.send_signal(signal.SIGTERM)
        assert worker.wait(timeout=60) == 0
        ready = MediaAsset.objects.get(pk=asset.pk)
        assert ready.status == MediaAsset.Status.READY and ready.attempts == 1
        assert rig.leftovers() == []

    def test_a_lost_message_is_replaced_when_the_worker_starts(self, rig, author, sample_clip):
        asset = new_asset(author, sample_clip)
        assert rig.enqueue(asset.pk) == "queued"
        for message in (rig.broker / "queue").iterdir():  # the message is lost
            message.unlink()
        MediaAsset.objects.filter(pk=asset.pk).update(enqueued_at=timezone.now())
        time.sleep(1.1)
        rig.start_worker()
        rig.wait_for(asset.pk, "ready")

    def test_a_broker_that_is_down_at_upload_time_is_caught_up_later(
        self, rig, author, sample_clip
    ):
        asset = new_asset(author, sample_clip)
        queue = rig.broker / "queue"
        queue.chmod(0o500)  # the broker can't be written to
        try:
            assert rig.enqueue(asset.pk) == "not queued"
        finally:
            queue.chmod(0o700)
        assert MediaAsset.objects.get(pk=asset.pk).status == MediaAsset.Status.UPLOADED
        time.sleep(1.1)
        rig.start_worker()  # recovery on start sees an asset nobody queued
        rig.wait_for(asset.pk, "ready")

    def test_repeated_failures_end_plainly_and_retry_works_once_fixed(
        self, rig, author, sample_clip
    ):
        asset = new_asset(author, sample_clip)
        rig.flags["fail"].write_text("")  # every transcode runs out of disk
        rig.start_worker()
        rig.enqueue(asset.pk)
        failed = rig.wait_for(asset.pk, "failed")
        assert failed.attempts == 3 and failed.retryable
        assert "ran out of storage space" in failed.error
        assert "No space left" not in failed.error
        assert (rig.media / failed.original_path).is_file()
        assert rig.transcodes() == 3

        rig.flags["fail"].unlink()  # space is freed up; the author presses Retry
        services.retry_asset(MediaAsset.objects.get(pk=asset.pk))
        rig.enqueue(asset.pk)
        ready = rig.wait_for(asset.pk, "ready")
        assert ready.attempts == 1 and ready.error == ""
