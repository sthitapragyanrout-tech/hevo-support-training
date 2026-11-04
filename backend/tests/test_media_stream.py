"""Playing a video: byte ranges (so seeking works), headers, and the nginx hand-off."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.media_pipeline import byterange
from tests.media_helpers import POSTER_BYTES, VIDEO_BYTES, ready_asset, video_course

SIZE = len(VIDEO_BYTES)


class TestParse:
    @pytest.mark.parametrize(
        "header,expected",
        [
            ("bytes=0-99", (0, 99)),
            ("bytes=100-", (100, SIZE - 1)),
            ("bytes=-500", (SIZE - 500, SIZE - 1)),
            ("bytes=0-0", (0, 0)),
            (f"bytes={SIZE - 1}-{SIZE - 1}", (SIZE - 1, SIZE - 1)),
            ("bytes=10-99999999", (10, SIZE - 1)),  # past the end is clamped
            ("bytes=-999999999", (0, SIZE - 1)),  # a suffix longer than the file is the file
            (" bytes=5-9 ", (5, 9)),
        ],
    )
    def test_satisfiable(self, header, expected):
        r = byterange.parse(header, SIZE)
        assert (r.start, r.end) == expected

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "",
            "bytes=",
            "bytes=-",
            "items=0-9",
            "bytes=0-9,20-29",  # several ranges: serve the whole file
            "bytes=5-2",
            "bytes=a-b",
            "bytes=-5-9",
            "0-9",
            "bytes=" + "9" * 40 + "-",  # absurdly large numbers aren't parsed at all
        ],
    )
    def test_ignored_means_the_whole_file(self, header):
        assert byterange.parse(header, SIZE) is None

    @pytest.mark.parametrize(
        "header", [f"bytes={SIZE}-", f"bytes={SIZE + 5}-{SIZE + 9}", "bytes=-0"]
    )
    def test_unsatisfiable(self, header):
        with pytest.raises(byterange.Unsatisfiable):
            byterange.parse(header, SIZE)

    def test_an_empty_file_has_no_valid_range(self):
        with pytest.raises(byterange.Unsatisfiable):
            byterange.parse("bytes=0-", 0)


@pytest.fixture
def playing(client, make_role_user, media_dirs):
    uploader = make_role_user(Role.Name.TRAINER, username="up", email="up@example.com")
    asset = ready_asset(uploader, media_dirs)
    video_course(make_role_user, asset)
    learner = make_role_user(Role.Name.LEARNER, username="viewer", email="v@example.com")
    client.force_login(learner)
    return client, asset


@pytest.mark.django_db
class TestResponses:
    def url(self, asset):
        return reverse("media_api:video", args=[asset.pk])

    def test_whole_file(self, playing):
        client, asset = playing
        response = client.get(self.url(asset))
        assert response.status_code == 200
        assert response["Content-Length"] == str(SIZE)
        assert response["Accept-Ranges"] == "bytes"
        assert response["Content-Type"] == "video/mp4"
        assert b"".join(response.streaming_content) == VIDEO_BYTES

    def test_a_range_is_exactly_those_bytes(self, playing):
        client, asset = playing
        response = client.get(self.url(asset), HTTP_RANGE="bytes=300-599")
        assert response.status_code == 206
        assert response["Content-Range"] == f"bytes 300-599/{SIZE}"
        assert response["Content-Length"] == "300"
        assert b"".join(response.streaming_content) == VIDEO_BYTES[300:600]

    @pytest.mark.parametrize(
        "header,start,end",
        [
            ("bytes=-100", SIZE - 100, SIZE - 1),
            ("bytes=10000-", 10000, SIZE - 1),
            ("bytes=0-0", 0, 0),
        ],
    )
    def test_open_ended_and_suffix_ranges(self, playing, header, start, end):
        client, asset = playing
        response = client.get(self.url(asset), HTTP_RANGE=header)
        assert response.status_code == 206
        assert b"".join(response.streaming_content) == VIDEO_BYTES[start : end + 1]
        assert response["Content-Range"] == f"bytes {start}-{end}/{SIZE}"

    def test_a_range_past_the_end_is_416_and_says_how_long_the_file_is(self, playing):
        client, asset = playing
        response = client.get(self.url(asset), HTTP_RANGE=f"bytes={SIZE + 10}-")
        assert response.status_code == 416
        assert response["Content-Range"] == f"bytes */{SIZE}"

    def test_a_garbled_range_just_serves_the_file(self, playing):
        client, asset = playing
        response = client.get(self.url(asset), HTTP_RANGE="bytes=oops")
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == VIDEO_BYTES

    def test_head_describes_without_sending(self, playing):
        client, asset = playing
        response = client.head(self.url(asset))
        assert response.status_code == 200 and response["Content-Length"] == str(SIZE)

    def test_the_poster_is_an_image(self, playing):
        client, asset = playing
        response = client.get(reverse("media_api:poster", args=[asset.pk]))
        assert response["Content-Type"] == "image/jpeg"
        assert b"".join(response.streaming_content) == POSTER_BYTES

    def test_headers_keep_it_private_and_unsniffable(self, playing):
        client, asset = playing
        response = client.get(self.url(asset))
        assert "private" in response["Cache-Control"]
        assert "public" not in response["Cache-Control"]
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "Cookie" in response["Vary"]

    def test_only_get_and_head(self, playing):
        client, asset = playing
        for method in (client.post, client.put, client.delete, client.patch):
            assert method(self.url(asset)).status_code in (403, 405)

    def test_nginx_can_take_over_after_we_have_authorised(self, playing, settings):
        client, asset = playing
        settings.MEDIA_ACCEL_REDIRECT = "/protected-media/"
        response = client.get(self.url(asset), HTTP_RANGE="bytes=0-9")
        assert response.status_code == 200
        assert response["X-Accel-Redirect"] == f"/protected-media/{asset.video_path}"
        assert response.content == b""

    def test_the_hand_off_never_skips_authorisation(self, playing, settings, client):
        _, asset = playing
        settings.MEDIA_ACCEL_REDIRECT = "/protected-media/"
        client.logout()
        response = client.get(self.url(asset))
        assert response.status_code == 403 and "X-Accel-Redirect" not in response
