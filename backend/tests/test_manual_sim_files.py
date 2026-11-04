"""Attachments: what is accepted, what is refused, that nothing is left behind, and that a
file can only be fetched by someone allowed to see the work. Types are decided from the
bytes, never from a name or a header."""

import struct
import zlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.manual_sim import assignments, files, services
from apps.manual_sim.errors import BadInput, TooLarge
from apps.manual_sim.models import SimSubmission, SubmissionFile
from apps.media_pipeline import services as media
from tests.manual_sim_helpers import at, jpeg, pdf, people, png, rated_course, webp

pytestmark = pytest.mark.django_db

ANSWER = "My reply."


@pytest.fixture
def world(make_role_user, media_dirs):
    return {**rated_course(make_role_user), **people(make_role_user)}


def upload(name, data, content_type="image/png"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def submit(world, uploads, who="learner"):
    return services.submit(world[who], world["activity"].pk, ANSWER, uploads=uploads, now=at())


def on_disk() -> list[str]:
    folder = media.media_root() / files.FOLDER
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def png_claiming(width: int, height: int) -> bytes:
    """A PNG whose header says it is enormous but which holds almost no data."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


# --------------------------------------------------------------------- what is refused


DISGUISED = {
    "html as png": upload("fine.png", b"<html><script>alert(1)</script></html>"),
    "exe as png": upload("fine.png", b"MZ\x90\x00" + b"\x00" * 200),
    "svg as png": upload(
        "fine.png", b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'
    ),
    "svg": upload("logo.svg", b"<svg></svg>", "image/svg+xml"),
    "zip as png": upload("fine.png", b"PK\x03\x04" + b"\x00" * 100),
    "text as pdf": upload("fine.pdf", b"just text", "application/pdf"),
    "gif as png": upload("fine.png", b"GIF89a" + b"\x00" * 40, "image/png"),
    "word as pdf": upload("fine.pdf", b"\xd0\xcf\x11\xe0" + b"\x00" * 200, "application/pdf"),
    "empty": upload("empty.png", b""),
}


class TestWhatIsRefused:
    @pytest.mark.parametrize("name", list(DISGUISED))
    def test_a_file_that_is_not_what_it_says_is_refused_and_leaves_nothing(self, world, name):
        with pytest.raises(BadInput):
            submit(world, [png(), DISGUISED[name]])
        assert SimSubmission.objects.count() == 0 and on_disk() == []

    def test_a_png_that_is_cut_short_is_refused(self, world):
        whole = png().read()
        with pytest.raises(BadInput) as caught:
            submit(world, [upload("cut.png", whole[: len(whole) // 2])])
        assert "damaged" in caught.value.message

    def test_a_jpeg_with_a_png_signature_is_refused(self, world):
        with pytest.raises(BadInput):
            submit(world, [upload("fake.png", b"\x89PNG\r\n\x1a\n" + jpeg().read())])

    def test_a_pdf_with_no_ending_is_refused(self, world):
        with pytest.raises(BadInput) as caught:
            submit(world, [upload("cut.pdf", b"%PDF-1.4\n" + b"x" * 5000, "application/pdf")])
        assert "incomplete or damaged" in caught.value.message

    def test_an_image_with_too_many_pixels_is_refused_without_decoding_it(self, world, settings):
        settings.MANUAL_SIM_MAX_PIXELS = 1_000_000
        with pytest.raises(BadInput) as caught:
            submit(world, [upload("huge.png", png_claiming(30_000, 30_000))])
        assert "too large" in caught.value.message or "damaged" in caught.value.message
        assert on_disk() == []

    def test_a_modest_image_over_the_pixel_cap_is_refused(self, world, settings):
        settings.MANUAL_SIM_MAX_PIXELS = 50
        with pytest.raises(BadInput):
            submit(world, [png(size=(20, 20))])
        assert submit(world, [png(size=(7, 7))]).files.count() == 1

    def test_the_size_limits(self, world, settings):
        settings.MANUAL_SIM_MAX_FILE_MB = 0.0001  # ~100 bytes
        with pytest.raises(TooLarge):
            submit(world, [png(size=(200, 200))])
        settings.MANUAL_SIM_MAX_FILE_MB = 10
        settings.MANUAL_SIM_MAX_TOTAL_MB = 0.0005
        with pytest.raises(TooLarge):
            submit(world, [pdf(body=b"a" * 400), pdf(body=b"b" * 400)])
        assert SimSubmission.objects.count() == 0 and on_disk() == []

    def test_too_many_files(self, world, settings):
        settings.MANUAL_SIM_MAX_FILES = 2
        with pytest.raises(BadInput):
            submit(world, [png(), png(), png()])
        assert submit(world, [png(), pdf()]).files.count() == 2


class TestWhatIsAcceptedAndHowItIsStored:
    def test_the_type_comes_from_the_bytes_not_the_name_or_the_header(self, world):
        lying = upload("report.pdf", jpeg().read(), "application/pdf")
        sub = submit(world, [lying])
        stored = sub.files.get()
        assert (stored.content_type, stored.extension) == ("image/jpeg", "jpg")

    def test_every_allowed_kind_is_accepted_and_kept_byte_for_byte(self, world):
        originals = [png(), jpeg(), webp(), pdf()]
        bytes_in = [u.read() for u in originals]
        for u in originals:
            u.seek(0)
        sub = submit(world, originals)
        kinds = [f.content_type for f in sub.files.all()]
        assert kinds == ["image/png", "image/jpeg", "image/webp", "application/pdf"]
        for stored, data in zip(sub.files.all(), bytes_in, strict=True):
            assert files.path_of(stored).read_bytes() == data  # never re-encoded

    def test_nothing_the_uploader_typed_reaches_the_file_system(self, world):
        names = ["../../../etc/passwd.png", "a\r\nb\x00.png", "C:\\x\\y.png", "x" * 400 + ".png"]
        sub = submit(world, [png(n) for n in names])
        for stored in sub.files.all():
            assert stored.relative_path == f"attachments/{stored.uuid}.png"
            assert "/" not in stored.original_name and "\\" not in stored.original_name
            assert all(ch.isprintable() for ch in stored.original_name)
        assert all(n.endswith(".png") and len(n) == 40 for n in on_disk())  # uuid + .png

    def test_a_long_name_is_bounded(self, world):
        sub = submit(world, [png("x" * 400 + ".png")])
        assert len(sub.files.get().original_name) <= 120

    def test_an_interrupted_upload_leaves_nothing_behind(self, world, monkeypatch):
        real = files.write
        calls = {"n": 0}

        def flaky(upload_, detected):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk fell over")
            return real(upload_, detected)

        monkeypatch.setattr(files, "write", flaky)
        with pytest.raises(OSError):
            submit(world, [png(), pdf()])
        assert SimSubmission.objects.count() == 0 and SubmissionFile.objects.count() == 0
        assert on_disk() == []  # the first file was removed too

    def test_a_failed_write_is_reported_in_a_sentence(self, world, monkeypatch):
        def full(*args, **kwargs):
            from apps.media_pipeline.errors import NoSpace

            raise NoSpace("There isn’t enough storage space right now. Please try again later.")

        monkeypatch.setattr(media, "_assert_free_space", full)
        with pytest.raises(Exception) as caught:
            submit(world, [png()])
        assert getattr(caught.value, "status_code", None) == 503


# --------------------------------------------------------------------------- serving


def url(stored):
    return reverse("rated_sim_api:file", args=[stored.uuid])


@pytest.fixture
def stored(world):
    sub = submit(world, [png("my shot.png"), pdf("notes.pdf")])
    return {
        "png": sub.files.get(extension="png"),
        "pdf": sub.files.get(extension="pdf"),
        "sub": sub,
    }


class TestServing:
    def get(self, client, who, world, stored_file):
        client.force_login(world[who])
        return client.get(url(stored_file))

    def test_an_image_is_shown_in_place_and_cannot_act_as_a_page(self, client, world, stored):
        r = self.get(client, "learner", world, stored["png"])
        assert r.status_code == 200 and r["Content-Type"] == "image/png"
        assert r["X-Content-Type-Options"] == "nosniff"
        assert r["Content-Security-Policy"] == "default-src 'none'; sandbox"
        assert r["Cache-Control"] == "private, no-cache" and "Cookie" in r["Vary"]
        assert r["Content-Disposition"].startswith("inline")
        assert b"".join(r.streaming_content) == files.path_of(stored["png"]).read_bytes()

    def test_a_pdf_is_always_a_download(self, client, world, stored):
        r = self.get(client, "learner", world, stored["pdf"])
        assert r["Content-Type"] == "application/pdf" and r["Content-Disposition"].startswith(
            "attachment"
        )
        assert "notes.pdf" in r["Content-Disposition"]

    def test_the_filename_cannot_break_out_of_the_header(self, client, world):
        sub = submit(world, [png("a\r\nSet-Cookie: x=1.png")])
        r = self.get(client, "learner", world, sub.files.get())
        assert "\r" not in r["Content-Disposition"] and "\n" not in r["Content-Disposition"]
        assert "Set-Cookie" not in r.headers

    def test_nginx_can_send_the_bytes_after_we_authorise(self, client, world, stored, settings):
        settings.MEDIA_ACCEL_REDIRECT = "/protected-media/"
        r = self.get(client, "learner", world, stored["png"])
        assert (
            r["X-Accel-Redirect"] == f"/protected-media/{stored['png'].relative_path}"
            and r.content == b""
        )

    @pytest.mark.parametrize(
        ("who", "assigned", "ok"),
        [
            ("learner", False, True),  # the author
            ("other", False, False),  # another learner
            ("mentor", False, True),  # pool: any rater may see it to rate it
            ("trainer", False, True),  # may rate/manage and see results
            ("root", False, True),
            ("mentor2", True, False),  # assigned to the other mentor: not this one
            ("mentor", True, True),  # assigned mentor
        ],
    )
    def test_who_may_fetch_it(self, client, world, who, assigned, ok):
        if assigned:
            assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = submit(world, [png()])
        r = self.get(client, who, world, sub.files.get())
        assert r.status_code == (200 if ok else 404)

    def test_a_stranger_gets_the_same_answer_as_a_missing_file(self, client, world, stored):
        client.force_login(world["other"])
        missing = client.get(
            reverse("rated_sim_api:file", args=["12345678-1234-5678-1234-567812345678"])
        )
        refused = client.get(url(stored["png"]))
        assert (
            missing.status_code == refused.status_code == 404 and missing.content == refused.content
        )

    def test_signed_out_gets_nothing(self, client, world, stored):
        assert client.get(url(stored["png"])).status_code in (401, 403)

    def test_a_file_missing_from_disk_is_a_404_not_a_crash(self, client, world, stored):
        files.path_of(stored["png"]).unlink()
        assert self.get(client, "learner", world, stored["png"]).status_code == 404

    def test_a_stored_path_outside_its_folder_is_never_served(self, client, world, stored):
        SubmissionFile.objects.filter(pk=stored["png"].pk).update(extension="../x")
        stored["png"].refresh_from_db()
        assert self.get(client, "learner", world, stored["png"]).status_code == 404


class TestUploadingOverHttp:
    def post(self, client, world, data, who="learner"):
        client.force_login(world[who])
        return client.post(reverse("rated_sim_api:submit", args=[world["activity"].pk]), data)

    def test_a_multipart_submission_with_files_and_links(self, client, world):
        r = self.post(
            client,
            world,
            {
                "answer": ANSWER,
                "links": ["https://docs.hevodata.com/x", "http://a.io"],
                "files": [png(), pdf()],
            },
        )
        assert r.status_code == 201, r.content
        revision = r.json()["revisions"][0]
        assert len(revision["files"]) == 2 and revision["links"] == [
            "https://docs.hevodata.com/x",
            "http://a.io",
        ]
        assert revision["files"][0]["url"].startswith("/api/v1/rated-sims/files/")

    def test_a_body_over_the_limit_is_stopped_and_nothing_is_stored(self, client, world, settings):
        settings.MANUAL_SIM_MAX_TOTAL_MB = 0.001  # ~1 KB
        big = pdf(body=b"z" * 20_000)
        r = self.post(client, world, {"answer": ANSWER, "files": [big]})
        assert r.status_code == 413 and SimSubmission.objects.count() == 0 and on_disk() == []

    def test_a_refusal_is_a_sentence_and_nothing_is_stored(self, client, world):
        r = self.post(client, world, {"answer": ANSWER, "files": [DISGUISED["html as png"]]})
        assert r.status_code == 400 and "can’t use that kind of file" in r.json()["detail"]
        assert SimSubmission.objects.count() == 0 and on_disk() == []

    def test_a_json_submission_without_files_works(self, client, world):
        client.force_login(world["learner"])
        r = client.post(
            reverse("rated_sim_api:submit", args=[world["activity"].pk]),
            {"answer": ANSWER, "links": ["https://x.io"]},
            content_type="application/json",
        )
        assert r.status_code == 201 and r.json()["case"]["status"] == "waiting"

    def test_the_filesystem_is_not_listed_or_leaked_in_any_response(self, client, world):
        r = self.post(client, world, {"answer": ANSWER, "files": [png()]})
        text = r.content.decode()
        assert str(media.media_root()) not in text and "attachments/" not in text
