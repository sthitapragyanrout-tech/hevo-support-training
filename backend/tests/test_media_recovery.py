"""When something goes wrong around the worker — a lost message, a killed
process, a down broker, debris — the database-driven sweeper puts it right."""

import os
import time
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError

from apps.accounts.models import Role
from apps.media_pipeline import services, tasks
from apps.media_pipeline.models import MediaAsset

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(media_dirs, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.MEDIA_MAX_ATTEMPTS = 3
    settings.MEDIA_REQUEUE_AFTER_SECONDS = 120


@pytest.fixture
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(services, "enqueue", lambda asset_id, **kw: sent.append(asset_id) or True)
    return sent


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER)


def asset(author, **fields) -> MediaAsset:
    defaults = {
        "uploaded_by": author,
        "original_name": "a.mp4",
        "size_bytes": 10,
        "duration_seconds": 2.0,
        "original_path": "originals/x.mp4",
    }
    defaults.update(fields)
    return MediaAsset.objects.create(**defaults)


def ago(seconds):
    return timezone.now() - timedelta(seconds=seconds)


class TestRequeue:
    def test_a_waiting_asset_that_was_never_queued_is_queued(self, author, queued):
        a = asset(author, enqueued_at=None)
        assert services.recover_stuck_assets()["requeued"] == 1
        assert queued == [a.pk]

    def test_a_recently_queued_asset_is_left_alone(self, author, queued):
        asset(author, enqueued_at=ago(10))
        assert services.recover_stuck_assets()["requeued"] == 0
        assert queued == []

    def test_a_message_that_was_lost_is_replaced(self, author, queued):
        a = asset(author, enqueued_at=ago(600))
        assert services.recover_stuck_assets()["requeued"] == 1
        assert queued == [a.pk]

    def test_finished_assets_are_not_requeued(self, author, queued):
        for state in (MediaAsset.Status.READY, MediaAsset.Status.FAILED):
            asset(author, status=state, enqueued_at=None)
        services.recover_stuck_assets()
        assert queued == []


class TestDeadWorkers:
    def test_an_expired_lease_is_released_and_queued_again(self, author, queued):
        a = asset(
            author,
            status=MediaAsset.Status.PROCESSING,
            attempts=1,
            claimed_at=ago(4000),
            lease_expires_at=ago(10),
        )
        counts = services.recover_stuck_assets()
        a.refresh_from_db()
        assert counts["released"] == 1 and counts["requeued"] == 1
        assert a.status == MediaAsset.Status.UPLOADED and a.lease_expires_at is None
        assert queued == [a.pk]

    def test_a_live_lease_is_never_touched(self, author, queued):
        a = asset(
            author,
            status=MediaAsset.Status.PROCESSING,
            attempts=1,
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        services.recover_stuck_assets()
        a.refresh_from_db()
        assert a.status == MediaAsset.Status.PROCESSING and queued == []

    def test_too_many_dead_workers_fails_with_a_plain_message(self, author, queued):
        a = asset(author, status=MediaAsset.Status.PROCESSING, attempts=3, lease_expires_at=ago(10))
        assert services.recover_stuck_assets()["failed"] == 1
        a.refresh_from_db()
        assert a.status == MediaAsset.Status.FAILED and a.retryable
        assert "couldn’t process this video" in a.error
        assert queued == []

    def test_a_waiting_asset_out_of_attempts_is_failed_not_looped_forever(self, author, queued):
        a = asset(author, attempts=3, enqueued_at=None)
        assert services.recover_stuck_assets()["failed"] == 1
        a.refresh_from_db()
        assert a.status == MediaAsset.Status.FAILED and queued == []

    def test_running_the_sweeper_twice_changes_nothing_the_second_time(self, author, queued):
        asset(author, enqueued_at=None)
        services.recover_stuck_assets()
        before = list(queued)
        # Pretend the queued message is in flight.
        MediaAsset.objects.update(enqueued_at=timezone.now())
        services.recover_stuck_assets()
        assert queued == before


class TestDebris:
    def test_old_temp_folders_of_dead_work_are_removed(self, author, media_dirs, queued):
        dead = asset(author, status=MediaAsset.Status.FAILED)
        folder = media_dirs / "tmp" / f"{dead.pk}-1"
        folder.mkdir(parents=True)
        (folder / "out.mp4").write_bytes(b"half")
        old = time.time() - 600
        os.utime(folder, (old, old))
        assert services.recover_stuck_assets()["debris"] == 1
        assert not folder.exists()

    def test_the_temp_folder_of_a_live_worker_is_kept(self, author, media_dirs, queued):
        live = asset(
            author,
            status=MediaAsset.Status.PROCESSING,
            attempts=1,
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        folder = media_dirs / "tmp" / f"{live.pk}-1"
        folder.mkdir(parents=True)
        old = time.time() - 600
        os.utime(folder, (old, old))
        services.recover_stuck_assets()
        assert folder.exists()

    def test_a_brand_new_temp_folder_is_not_raced(self, author, media_dirs, queued):
        folder = media_dirs / "tmp" / "999-1"
        folder.mkdir(parents=True)
        services.recover_stuck_assets()
        assert folder.exists()

    def test_half_written_uploads_are_cleared_after_an_hour(self, media_dirs, queued):
        part = media_dirs / "originals" / "x.mp4.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(b"partial")
        services.recover_stuck_assets()
        assert part.exists()  # recent: the upload may still be running
        old = time.time() - 7200
        os.utime(part, (old, old))
        services.recover_stuck_assets()
        assert not part.exists()


class TestRetry:
    def failed(self, author, media_dirs, **fields):
        original = media_dirs / "originals" / "x.mp4"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"data")
        defaults = {
            "status": MediaAsset.Status.FAILED,
            "retryable": True,
            "attempts": 3,
            "error": "boom",
        }
        defaults.update(fields)
        return asset(author, **defaults)

    def test_retry_resets_and_queues(
        self, author, media_dirs, queued, django_capture_on_commit_callbacks
    ):
        a = self.failed(author, media_dirs)
        with django_capture_on_commit_callbacks(execute=True):
            services.retry_asset(a)
        a.refresh_from_db()
        assert a.status == MediaAsset.Status.UPLOADED and a.attempts == 0 and a.error == ""
        assert queued == [a.pk]

    def test_cannot_retry_what_cannot_succeed(self, author, media_dirs, queued):
        for fields in (
            {"retryable": False},
            {"status": MediaAsset.Status.READY},
            {"original_path": ""},
            {"original_path": "originals/gone.mp4"},
            {"original_path": "../etc/hosts"},
        ):
            a = self.failed(author, media_dirs, **fields)
            with pytest.raises(services.MediaError):
                services.retry_asset(a)

    def test_the_retry_endpoint(self, client, author, media_dirs, queued):
        client.force_login(author)
        a = self.failed(author, media_dirs)
        response = client.post(reverse("media_authoring_api:retry", args=[a.pk]))
        assert response.status_code == 200
        assert response.json()["status"] == MediaAsset.Status.UPLOADED

    def test_the_retry_endpoint_refuses_the_impossible(self, client, author, media_dirs, queued):
        client.force_login(author)
        a = self.failed(author, media_dirs, retryable=False)
        response = client.post(reverse("media_authoring_api:retry", args=[a.pk]))
        assert response.status_code == 409


class TestBrokerDown:
    def test_enqueue_reports_failure_instead_of_raising(self, author, monkeypatch):
        a = asset(author)

        def down(*args, **kwargs):
            raise OperationalError("broker unreachable")

        monkeypatch.setattr(tasks.transcode_asset, "apply_async", down)
        assert services.enqueue(a.pk) is False

    def test_any_kind_of_broker_failure_is_survived(self, author, monkeypatch):
        a = asset(author)

        def weird(*args, **kwargs):
            raise UnboundLocalError("kombu's filesystem transport does this")

        monkeypatch.setattr(tasks.transcode_asset, "apply_async", weird)
        assert services.enqueue(a.pk) is False

    def test_eager_mode_does_not_hide_a_tasks_own_errors(self, author, settings, monkeypatch):
        a = asset(author)
        settings.CELERY_TASK_ALWAYS_EAGER = True

        def bug(*args, **kwargs):
            raise RuntimeError("a real bug")

        monkeypatch.setattr(tasks.transcode_asset, "apply_async", bug)
        with pytest.raises(RuntimeError):
            services.enqueue(a.pk)

    def test_an_upload_still_succeeds_and_the_sweeper_queues_it_later(
        self, client, author, sample_clip, monkeypatch, django_capture_on_commit_callbacks
    ):
        calls = []

        def down(*args, **kwargs):
            calls.append(1)
            raise OperationalError("broker unreachable")

        monkeypatch.setattr(tasks.transcode_asset, "apply_async", down)
        client.force_login(author)
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                reverse("media_authoring_api:upload"),
                {"file": SimpleUploadedFile("a.mp4", sample_clip.read_bytes())},
            )
        assert response.status_code == 201 and calls
        a = MediaAsset.objects.get(pk=response.json()["id"])
        assert a.status == MediaAsset.Status.UPLOADED

        # The broker comes back; the sweeper (marked "not yet queued" by the
        # failed attempt's stale timestamp) sends it.
        sent = []
        monkeypatch.setattr(
            tasks.transcode_asset, "apply_async", lambda args, **kw: sent.append(args[0])
        )
        MediaAsset.objects.filter(pk=a.pk).update(enqueued_at=ago(600))
        assert services.recover_stuck_assets()["requeued"] == 1
        assert sent == [a.pk]


class TestPolling:
    def test_the_uploader_can_poll_but_nobody_else(self, client, author, make_role_user):
        a = asset(author)
        url = reverse("media_authoring_api:detail", args=[a.pk])
        client.force_login(author)
        assert client.get(url).status_code == 200
        client.logout()

        other = make_role_user(Role.Name.TRAINER, username="other", email="o@example.com")
        client.force_login(other)
        assert client.get(url).status_code == 404  # same answer as "no such asset"
        client.logout()

        learner = make_role_user(Role.Name.LEARNER, username="l", email="l@example.com")
        client.force_login(learner)
        assert client.get(url).status_code == 403
        client.logout()
        assert client.get(url).status_code in (401, 403)

    def test_an_administrator_can_poll_any_asset(self, client, author, make_role_user):
        a = asset(author)
        client.force_login(make_role_user(Role.Name.ADMIN))
        assert client.get(reverse("media_authoring_api:detail", args=[a.pk])).status_code == 200

    def test_unknown_assets_are_404(self, client, author):
        client.force_login(author)
        assert client.get(reverse("media_authoring_api:detail", args=[424242])).status_code == 404

    def test_nothing_in_the_payload_reveals_a_path(self, client, author):
        a = asset(
            author,
            status=MediaAsset.Status.READY,
            video_path="videos/secret.mp4",
            poster_path="posters/secret.jpg",
        )
        client.force_login(author)
        text = client.get(reverse("media_authoring_api:detail", args=[a.pk])).content.decode()
        assert "secret" not in text and "originals/" not in text
