"""Turning an upload into a playable video — and, just as important, what
happens (and what is kept) when it does not work."""

import errno
import subprocess
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role
from apps.media_pipeline import ffmpeg, services
from apps.media_pipeline.models import MediaAsset
from tests.media_helpers import make_clip, needs_ffmpeg

pytestmark = [pytest.mark.django_db, needs_ffmpeg]


@pytest.fixture(autouse=True)
def _env(media_dirs, settings, monkeypatch):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.MEDIA_MAX_ATTEMPTS = 3
    # Retries are queued, not run inline, so each test controls every attempt.
    queued = []
    monkeypatch.setattr(services, "enqueue", lambda asset_id, **kw: queued.append(asset_id) or True)
    return queued


@pytest.fixture
def queued(_env):
    return _env


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER)


def make_asset(author, clip, name="lesson.mp4") -> MediaAsset:
    return services.create_asset(SimpleUploadedFile(name, clip.read_bytes()), author)


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def probe_all(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    import json

    return json.loads(out.stdout)


class TestHappyPath:
    def test_ready_video_is_web_safe_with_a_poster(self, author, sample_clip, media_dirs):
        asset = make_asset(author, sample_clip)
        assert services.process_asset(asset.pk) == "ready"
        asset.refresh_from_db()
        assert asset.status == MediaAsset.Status.READY
        video = media_dirs / asset.video_path
        poster = media_dirs / asset.poster_path
        assert video.is_file() and poster.is_file()
        # `faststart`: the index precedes the data, so the player can start (and
        # seek) without downloading the whole file first.
        head = video.read_bytes()
        assert head.index(b"moov") < head.index(b"mdat")
        assert poster.read_bytes()[:3] == b"\xff\xd8\xff"  # a JPEG
        info = probe_all(video)
        kinds = [s["codec_name"] for s in info["streams"]]
        assert kinds == ["h264", "aac"]
        assert asset.output_size_bytes == video.stat().st_size
        assert len(asset.output_sha256) == 64
        assert abs(asset.duration_seconds - 2) < 0.6
        assert asset.error == "" and asset.attempts == 1

    def test_the_original_is_deleted_only_after_ready(self, author, sample_clip, media_dirs):
        asset = make_asset(author, sample_clip)
        original = media_dirs / asset.original_path
        assert original.is_file()
        services.process_asset(asset.pk)
        asset.refresh_from_db()
        assert not original.exists()
        assert asset.original_purged and asset.original_path == ""
        assert files(media_dirs) == sorted([asset.video_path, asset.poster_path])

    def test_originals_can_be_kept(self, author, sample_clip, media_dirs, settings):
        settings.MEDIA_KEEP_ORIGINALS = True
        asset = make_asset(author, sample_clip)
        services.process_asset(asset.pk)
        asset.refresh_from_db()
        assert (media_dirs / asset.original_path).is_file()
        assert not asset.original_purged

    def test_big_pictures_are_scaled_down_and_odd_sizes_made_even(
        self, author, tmp_path, media_dirs
    ):
        big = make_clip(tmp_path / "big.mp4", size="1920x1080")
        asset = make_asset(author, big)
        services.process_asset(asset.pk)
        asset.refresh_from_db()
        assert (asset.width, asset.height) == (1280, 720)

        # An odd-sized source (yuv420p can't hold one, so it is 4:4:4).
        odd = tmp_path / "odd.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "testsrc=duration=2:size=322x242:rate=15", "-vf", "crop=321:241",
             "-c:v", "libx264", "-pix_fmt", "yuv444p", str(odd)],
            check=True,
        )  # fmt: skip
        asset2 = make_asset(author, odd)
        assert services.process_asset(asset2.pk) == "ready"
        asset2.refresh_from_db()
        assert asset2.width % 2 == 0 and asset2.height % 2 == 0

    def test_only_one_audio_and_the_video_stream_are_kept(self, author, tmp_path, media_dirs):
        multi = tmp_path / "multi.mkv"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
             "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-c:a", "aac", str(multi)],
            check=True,
        )  # fmt: skip
        asset = make_asset(author, multi, name="multi.mkv")
        assert services.process_asset(asset.pk) == "ready"
        asset.refresh_from_db()
        types = [s["codec_type"] for s in probe_all(media_dirs / asset.video_path)["streams"]]
        assert sorted(types) == ["audio", "video"]

    def test_a_silent_video_is_fine(self, author, tmp_path, media_dirs):
        silent = make_clip(tmp_path / "silent.mp4", audio=False)
        asset = make_asset(author, silent)
        assert services.process_asset(asset.pk) == "ready"

    def test_no_debris_is_left_in_the_temp_folder(self, author, sample_clip, media_dirs):
        asset = make_asset(author, sample_clip)
        services.process_asset(asset.pk)
        assert not (media_dirs / "tmp").exists() or not any((media_dirs / "tmp").iterdir())


class TestClaiming:
    def test_only_a_waiting_asset_can_be_claimed(self, author, sample_clip):
        asset = make_asset(author, sample_clip)
        assert services.claim(asset.pk).status == MediaAsset.Status.PROCESSING
        assert services.claim(asset.pk) is None  # a second worker with the same message

    def test_finished_and_missing_assets_are_no_ops(self, author, sample_clip):
        asset = make_asset(author, sample_clip)
        assert services.process_asset(asset.pk) == "ready"
        assert services.process_asset(asset.pk) == "skipped"
        assert services.process_asset(987654) == "skipped"
        asset.refresh_from_db()
        assert asset.attempts == 1  # the duplicate did no work

    def test_a_failed_asset_is_not_reprocessed_by_a_stray_message(self, author, sample_clip):
        asset = make_asset(author, sample_clip)
        MediaAsset.objects.filter(pk=asset.pk).update(status=MediaAsset.Status.FAILED)
        assert services.process_asset(asset.pk) == "skipped"


class TestFailuresKeepTheOriginal:
    def asset_and_original(self, author, sample_clip, media_dirs):
        asset = make_asset(author, sample_clip)
        return asset, media_dirs / asset.original_path

    def assert_untouched(self, asset, original, media_dirs):
        asset.refresh_from_db()
        assert original.is_file(), "the original must survive a failed transcode"
        assert not asset.original_purged and asset.original_path
        assert asset.status != MediaAsset.Status.READY
        assert files(media_dirs) == [asset.original_path], "no partial output left behind"

    @pytest.mark.parametrize("stage", ["transcode", "poster"])
    def test_a_full_disk_is_retried_and_loses_nothing(
        self, author, sample_clip, media_dirs, monkeypatch, queued, stage
    ):
        def boom(*a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(ffmpeg, stage, boom)
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        assert services.process_asset(asset.pk) == "retry"
        self.assert_untouched(asset, original, media_dirs)
        assert asset.status == MediaAsset.Status.UPLOADED and queued == [asset.pk]

    def test_running_out_of_attempts_fails_with_a_plain_retryable_message(
        self, author, sample_clip, media_dirs, monkeypatch
    ):
        def boom(*a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(ffmpeg, "transcode", boom)
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        outcomes = [services.process_asset(asset.pk) for _ in range(3)]
        assert outcomes == ["retry", "retry", "failed"]
        self.assert_untouched(asset, original, media_dirs)
        assert asset.status == MediaAsset.Status.FAILED and asset.retryable
        assert "ran out of storage space" in asset.error
        assert "errno" not in asset.error.lower() and "No space left" not in asset.error

    def test_a_disk_error_during_the_final_move_publishes_nothing(
        self, author, sample_clip, media_dirs, monkeypatch
    ):
        real = services.os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:  # the poster, after the video already moved
                raise OSError(errno.EIO, "I/O error")
            return real(src, dst)

        monkeypatch.setattr(services.os, "replace", flaky)
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        # (the upload itself used one replace before we started counting)
        calls.clear()
        assert services.process_asset(asset.pk) == "retry"
        self.assert_untouched(asset, original, media_dirs)

    def test_the_converter_failing_outright_is_not_retried(
        self, author, sample_clip, media_dirs, monkeypatch, queued
    ):
        def refuse(*a, **k):
            raise ffmpeg.PermanentError("We couldn’t convert that video. Try exporting it again.")

        monkeypatch.setattr(ffmpeg, "transcode", refuse)
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        assert services.process_asset(asset.pk) == "failed"
        self.assert_untouched(asset, original, media_dirs)
        assert asset.status == MediaAsset.Status.FAILED and not asset.retryable
        assert queued == []

    def test_a_timeout_is_a_retry(self, author, sample_clip, media_dirs, monkeypatch):
        def slow(*a, **k):
            raise subprocess.TimeoutExpired("ffmpeg", 1)

        monkeypatch.setattr(ffmpeg, "_run", slow)
        monkeypatch.setattr(
            services.ffmpeg, "probe", lambda p: ffmpeg.VideoInfo(2, 320, 240, "h264", True)
        )
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        assert services.process_asset(asset.pk) == "retry"
        self.assert_untouched(asset, original, media_dirs)

    @pytest.mark.parametrize("damage", ["empty", "truncated", "wrong_codec", "wrong_length"])
    def test_output_that_fails_verification_never_replaces_the_original(
        self, author, sample_clip, media_dirs, monkeypatch, tmp_path, damage
    ):
        real = ffmpeg.transcode
        other = make_clip(tmp_path / "other.mp4", seconds=5, codec="mpeg4")

        def damaged(src, dest, **kw):
            if damage == "empty":
                dest.write_bytes(b"")
            elif damage == "truncated":
                real(src, dest, **kw)
                data = dest.read_bytes()
                dest.write_bytes(data[: len(data) // 4])
            elif damage == "wrong_codec":
                dest.write_bytes(
                    make_clip(tmp_path / "mp4v.mp4", seconds=2, codec="mpeg4").read_bytes()
                )
            else:  # a complete, valid H.264 file — but 3 seconds longer than the source
                make = make_clip(tmp_path / "long.mp4", seconds=5)
                dest.write_bytes(make.read_bytes())

        monkeypatch.setattr(ffmpeg, "transcode", damaged)
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        assert services.process_asset(asset.pk) == "retry"
        self.assert_untouched(asset, original, media_dirs)
        assert other.exists()

    def test_the_original_going_missing_is_a_clear_failure(self, author, sample_clip, media_dirs):
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        original.unlink()
        assert services.process_asset(asset.pk) == "failed"
        asset.refresh_from_db()
        assert "no longer available" in asset.error and not asset.retryable

    def test_limits_are_checked_again_at_processing_time(
        self, author, sample_clip, media_dirs, settings
    ):
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        settings.MEDIA_MAX_DURATION_SECONDS = 1  # the limit was lowered after the upload
        assert services.process_asset(asset.pk) == "failed"
        asset.refresh_from_db()
        assert "longer than the" in asset.error
        assert original.is_file()

    def test_low_disk_at_the_start_of_processing_waits_and_retries(
        self, author, sample_clip, media_dirs, monkeypatch
    ):
        asset, original = self.asset_and_original(author, sample_clip, media_dirs)
        monkeypatch.setattr(services, "_free_bytes", lambda: 0)
        assert services.process_asset(asset.pk) == "retry"
        self.assert_untouched(asset, original, media_dirs)


class TestSafeDeletion:
    def ready_asset(self, author, sample_clip, settings):
        settings.MEDIA_KEEP_ORIGINALS = True
        asset = make_asset(author, sample_clip)
        services.process_asset(asset.pk)
        settings.MEDIA_KEEP_ORIGINALS = False
        asset.refresh_from_db()
        return asset

    def test_a_deletion_that_fails_leaves_a_ready_video_and_is_retried(
        self, author, sample_clip, media_dirs, monkeypatch
    ):
        from pathlib import Path

        asset = make_asset(author, sample_clip)
        real_unlink = Path.unlink

        def refuse(self, *a, **k):
            raise OSError(errno.EACCES, "denied")

        monkeypatch.setattr(Path, "unlink", refuse)
        assert services.process_asset(asset.pk) == "ready"
        monkeypatch.setattr(Path, "unlink", real_unlink)
        asset.refresh_from_db()
        assert asset.status == MediaAsset.Status.READY  # the learner-facing result is not at risk
        assert not asset.original_purged and (media_dirs / asset.original_path).is_file()
        # The sweeper finishes the job.
        assert services.recover_stuck_assets()["purged"] == 1
        asset.refresh_from_db()
        assert asset.original_purged and asset.original_path == ""

    def test_only_ready_assets_are_ever_purged(self, author, sample_clip, media_dirs):
        for state in (
            MediaAsset.Status.UPLOADED,
            MediaAsset.Status.PROCESSING,
            MediaAsset.Status.FAILED,
        ):
            asset = make_asset(author, sample_clip)
            MediaAsset.objects.filter(pk=asset.pk).update(status=state)
            assert services.purge_original(asset.pk) is False
            assert (media_dirs / asset.original_path).is_file()
            MediaAsset.objects.filter(pk=asset.pk).update(status=MediaAsset.Status.FAILED)

    @pytest.mark.parametrize(
        "bad_path", ["../outside.mp4", "videos/x.mp4", "/etc/hosts", "originals/../videos/x.mp4"]
    )
    def test_purge_never_touches_files_outside_originals(
        self, author, sample_clip, media_dirs, bad_path, tmp_path
    ):
        decoy = media_dirs / "videos" / "x.mp4"
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_bytes(b"precious")
        outside = media_dirs.parent / "outside.mp4"
        outside.write_bytes(b"precious")
        asset = make_asset(author, sample_clip)
        MediaAsset.objects.filter(pk=asset.pk).update(
            status=MediaAsset.Status.READY, original_path=bad_path
        )
        assert services.purge_original(asset.pk) is False
        assert decoy.read_bytes() == b"precious" and outside.read_bytes() == b"precious"


class TestProcessHandling:
    def test_a_runaway_process_and_its_children_are_killed_at_the_timeout(self):
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            ffmpeg._run(["sh", "-c", "sleep 30 & sleep 30 & wait"], timeout=0.5)
        assert time.monotonic() - started < 5
        leftover = subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True)
        assert leftover.returncode == 1, "child processes were left running"
