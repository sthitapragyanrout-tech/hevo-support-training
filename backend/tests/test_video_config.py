"""The video activity's configuration: who may attach an upload, what a learner
sees of it, what blocks publishing, and which YouTube links are accepted."""

import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.activities import registry, video
from apps.catalog import services as catalog
from apps.catalog.models import Activity
from apps.media_pipeline.models import MediaAsset
from tests.media_helpers import ready_asset

pytestmark = pytest.mark.django_db

YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def _media(media_dirs):
    return media_dirs


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER, username="author", email="author@example.com")


@pytest.fixture
def other_author(make_role_user):
    return make_role_user(Role.Name.TRAINER, username="other", email="other@example.com")


@pytest.fixture
def admin(make_role_user):
    return make_role_user(Role.Name.ADMIN, username="boss", email="boss@example.com")


@pytest.fixture
def lesson(author):
    course = catalog.create_course(title="C", user=author)
    version = catalog.open_version(course)
    module = catalog.add_node(version.root_node, title="M")
    return catalog.add_node(module, title="L"), version


def api(client, user, method, name, *args, data=None):
    client.force_login(user)
    return getattr(client, method)(
        reverse(f"authoring_api:{name}", args=args),
        data=json.dumps(data or {}),
        content_type="application/json",
    )


class TestYouTubeLinks:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
            "http://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?si=abc",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "  https://youtu.be/dQw4w9WgXcQ  ",
        ],
    )
    def test_real_links_give_their_id(self, url):
        assert video.youtube_id(url) == "dQw4w9WgXcQ"

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            42,
            "https://example.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com.evil.io/watch?v=dQw4w9WgXcQ",
            "https://evil.io/youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com@evil.io/watch?v=dQw4w9WgXcQ",
            "javascript:alert(1)//youtube.com/watch?v=dQw4w9WgXcQ",
            "ftp://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ_toolong",
            "https://www.youtube.com/watch?v=<script>alert()",
            "https://www.youtube.com/watch",
            "https://www.youtube.com/",
            "https://youtu.be/",
            "not a url at all",
            "https://www.youtube.com/watch?v=" + "a" * 10_000,
        ],
    )
    def test_everything_else_is_refused(self, url):
        assert video.youtube_id(url) is None


class TestTrackingSettings:
    def test_defaults_and_bounds(self):
        assert video.threshold({}) == 0.9 and video.credited_rate({}) == 1.0
        assert video.threshold({"completion_threshold": 0.1}) == 0.5  # never trivially short
        assert video.threshold({"completion_threshold": 7}) == 1.0
        assert video.credited_rate({"max_credited_rate": 50}) == 2.0
        assert video.credited_rate({"max_credited_rate": 0}) == 0.25
        assert video.threshold({"completion_threshold": "0.2"}) == 0.9  # junk → the default
        assert video.threshold({"completion_threshold": True}) == 0.9


class TestAttachingAnUpload:
    """An author can only point a video at an upload they own."""

    def make_activity(self, client, user, lesson):
        node, _ = lesson
        response = api(
            client, user, "post", "node-activities", node.pk, data={"activity_type": "video"}
        )
        assert response.status_code == 201, response.content
        return response.json()["id"]

    def attach(self, client, user, activity_id, asset_id):
        return api(
            client, user, "patch", "activity", activity_id,
            data={"config": {"source": "upload", "media_asset": asset_id}},
        )  # fmt: skip

    def test_the_uploader_can(self, client, author, lesson, media_dirs):
        asset = ready_asset(author, media_dirs)
        activity_id = self.make_activity(client, author, lesson)
        response = self.attach(client, author, activity_id, asset.pk)
        assert response.status_code == 200
        assert response.json()["config"]["media_asset"] == asset.pk

    def test_another_author_cannot_borrow_it(
        self, client, author, other_author, lesson, media_dirs
    ):
        asset = ready_asset(author, media_dirs)
        activity_id = self.make_activity(client, author, lesson)
        response = self.attach(client, other_author, activity_id, asset.pk)
        assert response.status_code == 400
        assert "isn’t available to you" in response.json()["detail"]
        assert "media_asset" not in Activity.objects.get(pk=activity_id).config

    def test_an_administrator_can_use_any(self, client, author, admin, lesson, media_dirs):
        asset = ready_asset(author, media_dirs)
        activity_id = self.make_activity(client, author, lesson)
        assert self.attach(client, admin, activity_id, asset.pk).status_code == 200

    def test_an_asset_that_does_not_exist(self, client, author, lesson):
        activity_id = self.make_activity(client, author, lesson)
        assert self.attach(client, author, activity_id, 424242).status_code == 400

    def test_a_youtube_activity_needs_no_asset(self, client, author, lesson):
        activity_id = self.make_activity(client, author, lesson)
        response = api(
            client, author, "patch", "activity", activity_id,
            data={"config": {"source": "youtube", "youtube_url": YT}},
        )  # fmt: skip
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "config",
        [
            {"source": "vimeo"},
            {"source": "upload", "media_asset": "7"},
            {"source": "upload", "media_asset": 0},
            {"source": "upload", "media_asset": True},
            {"completion_threshold": 2},
            {"completion_threshold": 0.1},
            {"max_credited_rate": 9},
        ],
    )
    def test_bad_settings_are_refused(self, client, author, lesson, config):
        activity_id = self.make_activity(client, author, lesson)
        response = api(client, author, "patch", "activity", activity_id, data={"config": config})
        assert response.status_code == 400


class TestWhatABlocksPublishing:
    def checklist(self, version):
        return [i.message for i in catalog.publish_checklist(version)]

    def video_in(self, lesson, **config):
        node, version = lesson
        Activity.objects.create(
            content_node=node, activity_type="video", title="Watch", config=config
        )
        return version

    def test_a_new_video_needs_choosing(self, lesson):
        version = self.video_in(lesson, **registry.get_type("video").default_config)
        assert any("Upload a video" in m for m in self.checklist(version))

    @pytest.mark.parametrize("status", ["uploaded", "processing"])
    def test_an_unfinished_upload_blocks(self, lesson, author, media_dirs, status):
        asset = ready_asset(author, media_dirs, status=status)
        version = self.video_in(lesson, source="upload", media_asset=asset.pk)
        assert any("still processing" in m for m in self.checklist(version))

    def test_a_failed_upload_blocks_with_a_sentence(self, lesson, author, media_dirs):
        asset = ready_asset(author, media_dirs, status=MediaAsset.Status.FAILED)
        version = self.video_in(lesson, source="upload", media_asset=asset.pk)
        assert any("couldn’t be processed" in m for m in self.checklist(version))

    def test_a_missing_asset_blocks(self, lesson):
        version = self.video_in(lesson, source="upload", media_asset=999)
        assert any("can’t be found" in m for m in self.checklist(version))

    def test_a_ready_upload_is_fine(self, lesson, author, media_dirs):
        asset = ready_asset(author, media_dirs)
        version = self.video_in(lesson, source="upload", media_asset=asset.pk)
        assert not [m for m in self.checklist(version) if "Watch" in m]

    def test_a_bad_youtube_link_blocks(self, lesson):
        version = self.video_in(lesson, source="youtube", youtube_url="https://evil.io/x")
        assert any("valid YouTube link" in m for m in self.checklist(version))

    def test_a_good_youtube_link_is_fine(self, lesson):
        version = self.video_in(lesson, source="youtube", youtube_url=YT)
        assert not [m for m in self.checklist(version) if "Watch" in m]


class TestWhatALearnerSees:
    def view(self, config):
        return registry.learner_config("video", config)

    def test_an_upload_exposes_only_how_to_play_it(self, author, media_dirs):
        asset = ready_asset(author, media_dirs)
        shown = self.view({"source": "upload", "media_asset": asset.pk, "secret_note": "no"})
        assert shown == {
            "source": "upload",
            "completion_threshold": 0.9,
            "max_credited_rate": 1.0,
            "media_asset": asset.pk,
            "media_url": f"/api/v1/media/{asset.pk}/video/",
            "poster_url": f"/api/v1/media/{asset.pk}/poster/",
            "duration": 120.0,
        }
        text = json.dumps(shown)
        for private in (
            "Secret client demo",
            "never-shown",
            "videos/",
            ".mp4",
            "originals",
            "author",
        ):
            assert private not in text

    def test_an_unready_upload_has_nothing_to_play(self, author, media_dirs):
        asset = ready_asset(author, media_dirs, status="processing")
        shown = self.view({"source": "upload", "media_asset": asset.pk})
        assert "media_url" not in shown and "duration" not in shown

    def test_youtube_exposes_the_id_not_the_link(self):
        shown = self.view({"source": "youtube", "youtube_url": YT + "&list=private"})
        assert shown["youtube_id"] == "dQw4w9WgXcQ"
        assert "youtube_url" not in shown and "list=private" not in json.dumps(shown)

    def test_it_never_includes_anything_unlisted(self):
        shown = self.view(
            {"source": "youtube", "youtube_url": YT, "video_asset_ref": "x", "other": 1}
        )
        assert set(shown) == {"source", "completion_threshold", "max_credited_rate", "youtube_id"}


class TestCompletable:
    def test_only_a_playable_video_can_hold_a_lesson_up(self, author, media_dirs):
        ready = ready_asset(author, media_dirs)
        pending = ready_asset(author, media_dirs, status="processing")
        yes = [
            {"source": "upload", "media_asset": ready.pk},
            {"source": "youtube", "youtube_url": YT},
        ]
        no = [
            {},
            {"video_asset_ref": "legacy-placeholder"},
            {"source": "upload"},
            {"source": "upload", "media_asset": pending.pk},
            {"source": "upload", "media_asset": 12345},
            {"source": "youtube", "youtube_url": "https://evil.io"},
        ]
        assert all(registry.is_completable("video", c) for c in yes)
        assert not any(registry.is_completable("video", c) for c in no)


DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz_-12/view?usp=sharing"
DRIVE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz_-12"


class TestGoogleDriveLinks:
    @pytest.mark.parametrize(
        "url",
        [
            DRIVE,
            f"https://drive.google.com/file/d/{DRIVE_ID}/preview",
            f"https://drive.google.com/file/d/{DRIVE_ID}/view",
            f"https://drive.google.com/open?id={DRIVE_ID}",
            f"https://drive.google.com/uc?id={DRIVE_ID}&export=download",
            f"  http://drive.google.com/file/d/{DRIVE_ID}/view  ",
            f"https://drive.google.com/file/d/{DRIVE_ID}/view?resourcekey=abc",
        ],
    )
    def test_real_links_give_their_id(self, url):
        assert video.drive_id(url) == DRIVE_ID

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            7,
            f"https://example.com/file/d/{DRIVE_ID}/view",
            f"https://drive.google.com.evil.io/file/d/{DRIVE_ID}/view",
            f"https://evil.io/drive.google.com/file/d/{DRIVE_ID}/view",
            f"https://drive.google.com@evil.io/file/d/{DRIVE_ID}/view",
            f"https://docs.google.com/file/d/{DRIVE_ID}/view",
            f"javascript:alert(1)//drive.google.com/file/d/{DRIVE_ID}/view",
            f"ftp://drive.google.com/file/d/{DRIVE_ID}/view",
            "https://drive.google.com/file/d/short/view",
            "https://drive.google.com/file/d/<script>alert(1)</script>/view",
            "https://drive.google.com/drive/folders/" + DRIVE_ID,  # a folder, not a file
            "https://drive.google.com/",
            "https://drive.google.com/open",
            "https://drive.google.com/file/d/" + "a" * 5000 + "/view",
            "not a link",
        ],
    )
    def test_everything_else_is_refused(self, url):
        assert video.drive_id(url) is None

    def test_a_good_link_is_ready_to_publish_and_a_bad_one_blocks(self, lesson):
        node, version = lesson
        Activity.objects.create(
            content_node=node,
            activity_type="video",
            title="Watch",
            config={"source": "drive", "drive_url": "https://evil.io/x"},
        )
        messages = [i.message for i in catalog.publish_checklist(version)]
        assert any("valid Google Drive link" in m for m in messages)
        Activity.objects.update(config={"source": "drive", "drive_url": DRIVE})
        assert not [m for m in catalog.publish_checklist(version) if "Watch" in m]

    def test_a_learner_sees_the_id_not_the_link(self):
        shown = registry.learner_config(
            "video", {"source": "drive", "drive_url": DRIVE + "&secret=1", "x": 1}
        )
        assert shown["drive_id"] == DRIVE_ID
        assert "drive_url" not in shown and "secret" not in json.dumps(shown)
        assert set(shown) == {"source", "completion_threshold", "max_credited_rate", "drive_id"}

    def test_it_is_completable_only_with_a_real_link(self):
        assert registry.is_completable("video", {"source": "drive", "drive_url": DRIVE})
        assert not registry.is_completable(
            "video", {"source": "drive", "drive_url": "https://x.io"}
        )
        assert not registry.is_completable("video", {"source": "drive"})

    def test_an_author_can_save_a_drive_link(self, client, author, lesson):
        node, _ = lesson
        client.force_login(author)
        made = client.post(
            reverse("authoring_api:node-activities", args=[node.pk]),
            data=json.dumps({"activity_type": "video"}),
            content_type="application/json",
        ).json()["id"]
        response = api(
            client, author, "patch", "activity", made,
            data={"config": {"source": "drive", "drive_url": DRIVE}},
        )  # fmt: skip
        assert response.status_code == 200
