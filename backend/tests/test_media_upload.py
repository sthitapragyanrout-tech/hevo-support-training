"""Uploading a video: what is accepted, what is refused (with a plain sentence),
and that a refused upload leaves nothing behind."""

import errno

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Role
from apps.media_pipeline import services
from apps.media_pipeline.models import MediaAsset
from tests.media_helpers import make_clip, needs_ffmpeg

pytestmark = pytest.mark.django_db

UPLOAD = "media_authoring_api:upload"


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER)


@pytest.fixture
def author_client(client, author):
    client.force_login(author)
    return client


def upload(client, name="lesson.mp4", content=b"", **extra):
    return client.post(
        reverse(UPLOAD), {"file": SimpleUploadedFile(name, content, "video/mp4")}, **extra
    )


def clip_bytes(sample_clip) -> bytes:
    return sample_clip.read_bytes()


def files_on_disk(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


@pytest.fixture(autouse=True)
def _isolated(media_dirs, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False  # uploads queue; nothing runs inline here


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    """These tests are about the upload, not the worker: capture the queueing."""
    sent = []
    monkeypatch.setattr(services, "enqueue", lambda asset_id, **kw: sent.append(asset_id) or True)
    return sent


@needs_ffmpeg
class TestAccepted:
    def test_a_real_video_is_stored_and_queued(
        self, author_client, author, sample_clip, media_dirs, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = upload(author_client, content=clip_bytes(sample_clip))
        assert response.status_code == 201, response.content
        body = response.json()
        asset = MediaAsset.objects.get(pk=body["id"])
        assert asset.status == MediaAsset.Status.UPLOADED
        assert asset.uploaded_by == author
        assert 1.5 < asset.duration_seconds < 2.5
        assert (asset.width, asset.height) == (320, 240)
        assert files_on_disk(media_dirs) == [asset.original_path]
        # The Studio is told about the asset, never about a path on disk.
        assert "path" not in str(body).lower()
        assert body["video_url"] is None  # not playable until processed

    def test_the_stored_name_is_never_the_uploaded_name(
        self, author_client, sample_clip, media_dirs
    ):
        response = upload(
            author_client, name="../../etc/passwd\x00 evil.mp4", content=clip_bytes(sample_clip)
        )
        assert response.status_code == 201
        asset = MediaAsset.objects.get(pk=response.json()["id"])
        assert str(asset.uuid) in asset.original_path
        assert ".." not in asset.original_path and "evil" not in asset.original_path
        assert "\x00" not in asset.original_name


class TestRefused:
    def test_anonymous_cannot_upload(self, client):
        assert upload(client, content=b"x").status_code in (401, 403)

    def test_a_learner_cannot_upload(self, client, make_role_user):
        client.force_login(make_role_user(Role.Name.LEARNER))
        assert upload(client, content=b"x").status_code == 403

    def test_no_file(self, author_client):
        response = author_client.post(reverse(UPLOAD), {})
        assert response.status_code == 400
        assert "Choose a video file" in response.json()["detail"]

    @pytest.mark.parametrize("name", ["notes.txt", "malware.exe", "video", "clip.mp4.exe", ""])
    def test_the_wrong_kind_of_file(self, author_client, media_dirs, name):
        response = upload(author_client, name=name or "x", content=b"hello")
        assert response.status_code == 400
        assert "can’t use that kind of file" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []

    @needs_ffmpeg
    def test_text_pretending_to_be_a_video(self, author_client, media_dirs):
        response = upload(author_client, name="fake.mp4", content=b"this is not a video" * 100)
        assert response.status_code == 400
        assert "doesn’t look like a video" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []  # the partial file is gone
        assert MediaAsset.objects.count() == 0

    @needs_ffmpeg
    def test_audio_only_is_not_a_video(self, author_client, tmp_path, media_dirs):
        import subprocess

        wav = tmp_path / "tone.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2",
             "-c:a", "aac", "-f", "mp4", str(wav)],
            check=True,
        )  # fmt: skip
        response = upload(author_client, content=wav.read_bytes())
        assert response.status_code == 400
        assert "doesn’t contain a video" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []


@needs_ffmpeg
class TestLimits:
    def test_too_large_by_declared_size_is_refused_before_reading(
        self, author_client, settings, media_dirs
    ):
        settings.MEDIA_MAX_UPLOAD_MB = 0.001  # ~1 KB, plus the allowance for form overhead
        response = upload(author_client, content=b"x" * 200_000)
        assert response.status_code == 413
        assert "larger than the 0.001 MB limit" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []

    def test_the_stream_is_cut_off_at_the_limit(
        self, author_client, settings, sample_clip, media_dirs
    ):
        # Small enough to pass the up-front check, still over the limit: the
        # upload handler stops it as it arrives, so nothing is stored.
        settings.MEDIA_MAX_UPLOAD_MB = 0.01
        data = clip_bytes(sample_clip)
        assert services.max_upload_bytes() < len(data) < services.max_upload_bytes() + 64 * 1024
        response = upload(author_client, content=data)
        assert response.status_code == 413
        assert files_on_disk(media_dirs) == []
        assert MediaAsset.objects.count() == 0

    def test_the_handler_stops_reading_at_the_limit(self):
        from django.core.files.uploadhandler import StopUpload

        from apps.media_pipeline.views import LimitedUploadHandler

        handler = LimitedUploadHandler(None, 100)
        handler.new_file("file", "a.mp4", "video/mp4", 0)
        handler.receive_data_chunk(b"x" * 60, 0)
        with pytest.raises(StopUpload):
            handler.receive_data_chunk(b"x" * 60, 60)
        assert handler.exceeded

    def test_service_counts_bytes_while_copying(self, author, settings, media_dirs):
        upload_ = SimpleUploadedFile("a.mp4", b"x" * 5000)
        upload_.size = 10  # claims to be small; the bytes say otherwise
        settings.MEDIA_MAX_UPLOAD_MB = 0.0001  # ~100 bytes
        with pytest.raises(services.TooLarge):
            services.create_asset(upload_, author)
        assert files_on_disk(media_dirs) == []

    def test_too_long(self, author_client, settings, sample_clip, media_dirs):
        settings.MEDIA_MAX_DURATION_SECONDS = 1
        response = upload(author_client, content=clip_bytes(sample_clip))
        assert response.status_code == 400
        assert "longer than the" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []

    def test_too_short(self, author_client, tmp_path, media_dirs):
        short = make_clip(tmp_path / "short.mp4", seconds=0.3)
        response = upload(author_client, content=short.read_bytes())
        assert response.status_code == 400
        assert "too short" in response.json()["detail"]

    def test_picture_too_large(self, author_client, settings, sample_clip, media_dirs):
        settings.MEDIA_MAX_PIXELS = 1000
        response = upload(author_client, content=clip_bytes(sample_clip))
        assert response.status_code == 400
        assert "picture size" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []

    def test_unfinished_cap(self, author_client, author, settings, sample_clip):
        settings.MEDIA_MAX_UNFINISHED_PER_USER = 2
        for _ in range(2):
            assert upload(author_client, content=clip_bytes(sample_clip)).status_code == 201
        response = upload(author_client, content=clip_bytes(sample_clip))
        assert response.status_code == 429
        assert "still processing" in response.json()["detail"]
        # Finished videos don't count against the cap.
        MediaAsset.objects.update(status=MediaAsset.Status.READY)
        assert upload(author_client, content=clip_bytes(sample_clip)).status_code == 201

    def test_not_enough_disk_refuses_before_writing(
        self, author_client, monkeypatch, sample_clip, media_dirs
    ):
        monkeypatch.setattr(services, "_free_bytes", lambda: 0)
        response = upload(author_client, content=clip_bytes(sample_clip))
        assert response.status_code == 503
        assert "enough storage space" in response.json()["detail"]
        assert files_on_disk(media_dirs) == []

    def test_a_full_disk_while_writing_is_reported_plainly(
        self, author_client, monkeypatch, sample_clip, media_dirs
    ):
        real_replace = services.os.replace

        def boom(*a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(services.os, "replace", boom)
        response = upload(author_client, content=clip_bytes(sample_clip))
        monkeypatch.setattr(services.os, "replace", real_replace)
        assert response.status_code == 503
        assert "No space" not in response.json()["detail"]
        assert files_on_disk(media_dirs) == []
        assert MediaAsset.objects.count() == 0


class TestLimitsEndpoint:
    def test_authors_can_read_the_limits(self, author_client, settings):
        body = author_client.get(reverse("media_authoring_api:limits")).json()
        assert body["max_upload_mb"] == settings.MEDIA_MAX_UPLOAD_MB
        assert "mp4" in body["allowed_extensions"]

    def test_learners_cannot(self, client, make_role_user):
        client.force_login(make_role_user(Role.Name.LEARNER))
        assert client.get(reverse("media_authoring_api:limits")).status_code == 403
