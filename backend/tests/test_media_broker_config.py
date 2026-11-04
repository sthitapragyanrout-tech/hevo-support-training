"""The development broker is configured the way the recovery design assumes."""

import importlib
from pathlib import Path

import pytest
from django.conf import settings as django_settings

from config.celery import app as celery_app
from config.settings import base


class TestWorkerConfiguration:
    def test_one_message_at_a_time_acknowledged_late(self):
        assert celery_app.conf.worker_prefetch_multiplier == 1
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_state_lives_in_the_database_not_in_task_results(self):
        assert celery_app.conf.task_ignore_result is True

    def test_media_work_has_its_own_queue(self):
        assert celery_app.conf.task_default_queue == "media"
        assert celery_app.conf.task_routes["media_pipeline.*"] == {"queue": "media"}

    def test_the_tasks_are_registered(self):
        celery_app.loader.import_default_modules()
        assert "media_pipeline.transcode" in celery_app.tasks
        assert "media_pipeline.recover" in celery_app.tasks

    def test_recovery_runs_on_a_schedule(self):
        entry = celery_app.conf.beat_schedule["media-recover"]
        assert entry["task"] == "media_pipeline.recover" and entry["schedule"] <= 300

    def test_at_most_two_transcodes_at_once(self, monkeypatch):
        monkeypatch.setenv("MEDIA_WORKER_CONCURRENCY", "16")
        try:
            importlib.reload(base)
            assert base.MEDIA_WORKER_CONCURRENCY == 2
        finally:
            monkeypatch.undo()
            importlib.reload(base)


class TestFilesystemBroker:
    def test_the_transport_exists_in_this_environment(self):
        from kombu.transport import filesystem

        assert filesystem.Transport

    def test_defaults_use_it_and_keep_every_folder_outside_media(self):
        assert base.CELERY_BROKER_URL == "filesystem://"
        options = base.CELERY_BROKER_TRANSPORT_OPTIONS
        media = Path(base.MEDIA_ROOT).resolve()
        for key in ("data_folder_in", "data_folder_out", "control_folder", "processed_folder"):
            folder = Path(options[key]).resolve()
            assert media not in folder.parents and folder != media, key
            assert folder.is_dir(), f"{key} should exist"
        # One shared queue folder: what the web process writes, the worker reads.
        assert options["data_folder_in"] == options["data_folder_out"]

    def test_redis_gets_a_visibility_timeout_instead(self, monkeypatch):
        monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
        try:
            importlib.reload(base)
            assert base.CELERY_BROKER_TRANSPORT_OPTIONS == {"visibility_timeout": 7200}
        finally:
            monkeypatch.undo()
            importlib.reload(base)

    def test_the_running_app_uses_the_configured_folders(self):
        options = celery_app.conf.broker_transport_options
        assert (
            options["data_folder_in"]
            == django_settings.CELERY_BROKER_TRANSPORT_OPTIONS["data_folder_in"]
        )

    @pytest.mark.parametrize("name", ["MEDIA_ROOT", "CELERY_BROKER_FOLDER"])
    def test_test_runs_never_touch_the_real_folders(self, name):
        real = Path(base.BASE_DIR)
        assert real not in Path(str(getattr(django_settings, name))).resolve().parents
