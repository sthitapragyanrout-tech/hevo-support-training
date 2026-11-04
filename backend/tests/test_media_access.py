"""Who may play (or manage) an uploaded video — every actor, every state, both
files, and including requests for a locked lesson made directly by URL."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.media_pipeline.models import MediaAsset
from apps.progress.models import LessonCompletion
from tests.media_helpers import (
    POSTER_BYTES,
    VIDEO_BYTES,
    ready_asset,
    video_course,
)

pytestmark = pytest.mark.django_db


def video_url(asset_id):
    return reverse("media_api:video", args=[asset_id])


def poster_url(asset_id):
    return reverse("media_api:poster", args=[asset_id])


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
    return make_role_user(Role.Name.ADMIN, username="root", email="root@example.com")


@pytest.fixture
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="lena", email="lena@example.com")


@pytest.fixture
def second_learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="leo", email="leo@example.com")


def as_user(client, user):
    client.logout()
    if user is not None:
        client.force_login(user)
    return client


def status_of(client, user, url):
    return as_user(client, user).get(url).status_code


@pytest.fixture
def asset(author, media_dirs):
    return ready_asset(author, media_dirs)


# --------------------------------------------------------------- the matrix


class TestPublishedCourse:
    """A free (any-order) published course using the asset."""

    @pytest.fixture(autouse=True)
    def course(self, make_role_user, asset):
        return video_course(make_role_user, asset, order="free")

    @pytest.mark.parametrize("make_url", [video_url, poster_url])
    def test_who_can_play_it(self, client, asset, author, other_author, admin, learner, make_url):
        url = make_url(asset.pk)
        assert status_of(client, None, url) == 403  # anonymous
        assert status_of(client, learner, url) == 200
        assert status_of(client, author, url) == 200  # the uploader
        assert status_of(client, other_author, url) == 200  # a published course is public to staff
        assert status_of(client, admin, url) == 200

    def test_the_bytes_are_the_right_ones(self, client, asset, learner):
        as_user(client, learner)
        assert b"".join(client.get(video_url(asset.pk)).streaming_content) == VIDEO_BYTES
        assert b"".join(client.get(poster_url(asset.pk)).streaming_content) == POSTER_BYTES

    def test_archiving_the_course_cuts_off_the_next_request(self, client, asset, learner, course):
        as_user(client, learner)
        assert client.get(video_url(asset.pk), HTTP_RANGE="bytes=0-9").status_code == 206
        catalog.archive_course(course[0])
        assert client.get(video_url(asset.pk), HTTP_RANGE="bytes=10-19").status_code == 404
        assert client.get(poster_url(asset.pk)).status_code == 404
        catalog.restore_course(course[0])
        assert client.get(video_url(asset.pk), HTTP_RANGE="bytes=10-19").status_code == 206


class TestSequentialCourse:
    @pytest.fixture(autouse=True)
    def course(self, make_role_user, asset):
        self.built = video_course(make_role_user, asset, order="sequential")
        return self.built

    def test_a_locked_lesson_will_not_stream_even_by_direct_url(self, client, asset, learner):
        as_user(client, learner)
        for url in (video_url(asset.pk), poster_url(asset.pk)):
            response = client.get(url)
            assert response.status_code == 409
            assert response.json()["blocked_by"] == self.built[2].pk  # "First"
            assert "Finish “First” first" in response.json()["detail"]
        # …including the ranged requests a <video> element makes.
        assert client.get(video_url(asset.pk), HTTP_RANGE="bytes=0-99").status_code == 409

    def test_it_opens_the_moment_the_earlier_lesson_is_complete(
        self, client, asset, learner, second_learner
    ):
        LessonCompletion.objects.create(
            user=learner, node=self.built[2], completed_at=asset.created_at
        )
        assert status_of(client, learner, video_url(asset.pk)) == 200
        # …for that learner only.
        assert status_of(client, second_learner, video_url(asset.pk)) == 409

    def test_staff_who_authored_it_are_not_held_back_in_the_studio(
        self, client, asset, author, admin
    ):
        assert status_of(client, author, video_url(asset.pk)) == 200
        assert status_of(client, admin, video_url(asset.pk)) == 200

    def test_another_author_is_treated_as_a_learner_of_a_published_course(
        self, client, asset, other_author
    ):
        assert status_of(client, other_author, video_url(asset.pk)) == 409

    def test_an_asset_used_twice_opens_if_either_lesson_is_open(
        self, client, asset, learner, make_role_user
    ):
        # A second, ordinary course reuses the same video.
        video_course(make_role_user, asset, order="free", title="Other course")
        assert status_of(client, learner, video_url(asset.pk)) == 200


class TestDrafts:
    @pytest.fixture(autouse=True)
    def course(self, make_role_user, asset):
        return video_course(make_role_user, asset, publish=False)

    def test_a_draft_is_for_authors_not_learners(
        self, client, asset, author, other_author, admin, learner
    ):
        url = video_url(asset.pk)
        assert status_of(client, learner, url) == 404
        assert status_of(client, author, url) == 200
        assert status_of(client, other_author, url) == 200  # any author can preview a draft
        assert status_of(client, admin, url) == 200

    def test_a_published_course_with_a_newer_draft_still_streams_to_learners(
        self, client, asset, learner, make_role_user
    ):
        # Publish a course, then start a newer draft of it.
        built = video_course(make_role_user, asset, order="free", title="Live")
        catalog.get_or_create_draft(built[0])
        assert status_of(client, learner, video_url(asset.pk)) == 200


class TestEverythingElseIs404:
    def test_unknown_asset(self, client, learner, admin):
        assert status_of(client, learner, video_url(987654)) == 404
        assert status_of(client, admin, video_url(987654)) == 404

    def test_an_asset_no_course_uses(self, client, asset, author, other_author, learner, admin):
        url = video_url(asset.pk)
        assert status_of(client, learner, url) == 404
        assert status_of(client, other_author, url) == 404  # not theirs, not in any draft
        assert status_of(client, author, url) == 200  # the uploader
        assert status_of(client, admin, url) == 200

    def test_another_courses_video_is_not_reachable_through_this_one(
        self, client, author, learner, make_role_user, media_dirs
    ):
        mine = ready_asset(author, media_dirs)
        theirs = ready_asset(author, media_dirs)
        video_course(make_role_user, mine, title="Course A")
        video_course(make_role_user, theirs, order="sequential", title="Course B")
        assert status_of(client, learner, video_url(mine.pk)) == 200
        assert status_of(client, learner, video_url(theirs.pk)) == 409

    def test_an_asset_that_is_not_ready_has_nothing_to_play(
        self, client, author, learner, admin, make_role_user, media_dirs
    ):
        pending = ready_asset(author, media_dirs, status=MediaAsset.Status.PROCESSING)
        video_course(make_role_user, pending)
        for user in (learner, author, admin):
            assert status_of(client, user, video_url(pending.pk)) == 404
            assert status_of(client, user, poster_url(pending.pk)) == 404

    def test_a_tampered_path_is_refused(self, client, author, admin, media_dirs):
        asset = ready_asset(author, media_dirs)
        outside = media_dirs.parent / "outside.mp4"
        outside.write_bytes(b"not for you")
        for bad in ("../outside.mp4", "originals/x.mov", "/etc/hosts", "videos/../../outside.mp4"):
            MediaAsset.objects.filter(pk=asset.pk).update(video_path=bad)
            assert status_of(client, admin, video_url(asset.pk)) == 404, bad

    def test_a_ready_asset_whose_file_vanished(self, client, author, admin, media_dirs):
        asset = ready_asset(author, media_dirs)
        (media_dirs / asset.video_path).unlink()
        assert status_of(client, admin, video_url(asset.pk)) == 404

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/media/..%2f..%2fetc%2fpasswd/video/",
            "/api/v1/media/abc/video/",
            "/api/v1/media/1/original/",
            "/api/v1/media/1/../../auth/",
            "/media/videos/anything.mp4",
            "/api/v1/media/videos/anything.mp4",
        ],
    )
    def test_there_is_no_other_way_to_a_file(self, client, admin, path):
        assert as_user(client, admin).get(path).status_code == 404

    def test_originals_are_never_served(self, client, admin, author, media_dirs):
        asset = ready_asset(author, media_dirs)
        original = media_dirs / asset.original_path
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"the raw upload")
        as_user(client, admin)
        for suffix in ("original", "source", "raw"):
            assert client.get(f"/api/v1/media/{asset.pk}/{suffix}/").status_code == 404


class TestWatchingIsPerPerson:
    def test_one_learners_progress_does_not_open_the_video_for_another(
        self, client, asset, learner, second_learner, make_role_user
    ):
        built = video_course(make_role_user, asset, order="sequential")
        LessonCompletion.objects.create(user=learner, node=built[2], completed_at=asset.created_at)
        assert status_of(client, learner, video_url(asset.pk)) == 200
        assert status_of(client, second_learner, video_url(asset.pk)) == 409
        assert status_of(client, None, video_url(asset.pk)) == 403


class TestManagingAnAsset:
    """Poll and retry belong to the uploader (and administrators) only."""

    @pytest.mark.parametrize(
        "who,expected",
        [
            ("anonymous", (401, 403)),
            ("learner", (403,)),
            ("other_author", (404,)),
            ("author", (200,)),
            ("admin", (200,)),
        ],
    )
    def test_poll(self, client, asset, request, who, expected):
        user = None if who == "anonymous" else request.getfixturevalue(who)
        url = reverse("media_authoring_api:detail", args=[asset.pk])
        assert status_of(client, user, url) in expected

    def test_a_learner_in_a_published_course_still_cannot_poll(
        self, client, asset, learner, make_role_user
    ):
        video_course(make_role_user, asset)
        url = reverse("media_authoring_api:detail", args=[asset.pk])
        assert status_of(client, learner, url) == 403
