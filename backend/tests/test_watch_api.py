"""Verified watching, end to end through the API: what completes a video, what
doesn't, and everything a hostile or merely unlucky client can send."""

import json
import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity
from apps.progress import watch, watching
from apps.progress.models import ActivityProgress, LessonCompletion, VideoWatch
from tests.media_helpers import ready_asset, video_course

pytestmark = pytest.mark.django_db

DURATION = 120.0  # the fake asset's length
NEEDED = 0.9 * DURATION  # 108 s
S1, S2 = str(uuid.uuid4()), str(uuid.uuid4())
YT = "https://youtu.be/dQw4w9WgXcQ"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(watching, "_now", c)
    return c


@pytest.fixture(autouse=True)
def _env(media_dirs):
    cache.clear()  # the throttle lives in the cache


@pytest.fixture
def author(make_role_user):
    return make_role_user(Role.Name.TRAINER, username="author", email="author@example.com")


@pytest.fixture
def learner(make_role_user):
    return make_role_user(Role.Name.LEARNER, username="lena", email="lena@example.com")


@pytest.fixture
def course(author, make_role_user, media_dirs):
    asset = ready_asset(author, media_dirs)
    return video_course(make_role_user, asset, order="free")


@pytest.fixture
def activity(course):
    return course[4]


@pytest.fixture
def lc(client, learner):
    client.force_login(learner)
    return client


def watch_url(activity):
    return reverse("progress_api:activity-watch", args=[activity.pk])


def beat(client, activity, *, seq=0, ranges=(), session=S1, **overrides):
    body = {
        "session_id": session,
        "seq": seq,
        "ranges": [list(r) for r in ranges],
        "position": ranges[-1][1] if ranges else 0,
        "rate": 1,
        "hidden_seconds": 0,
    }
    body.update(overrides)
    return client.post(watch_url(activity), json.dumps(body), content_type="application/json")


def post_raw(client, activity, **body):
    """A heartbeat exactly as given (no tidying), for hostile payloads."""
    base = {
        "session_id": S1,
        "seq": 1,
        "ranges": [[5, 10]],
        "position": 10,
        "rate": 1,
        "hidden_seconds": 0,
    }
    base.update(body)
    return client.post(watch_url(activity), json.dumps(base), content_type="application/json")


def row(learner, activity):
    return VideoWatch.objects.get(user=learner, activity=activity)


def hello(client, activity, *, session=S1, seq=0):
    """What the player sends the moment playback starts: nothing claimed, but
    the server's clock now runs from here."""
    response = beat(client, activity, seq=seq, session=session, ranges=[], position=0)
    assert response.status_code == 200, response.content
    return response.json()


def play(client, clock, activity, seconds, *, step=15.0, start=0.0, session=S1):
    """Honest playback: it says hello when it starts, then real time passes as
    the video plays at 1× with a heartbeat every `step` seconds."""
    seqs = client.__dict__.setdefault("_watch_seqs", {})
    key = (activity.pk, session)
    if key not in seqs:
        hello(client, activity, session=session)
        seqs[key] = 1
    position, last = start, None
    while position < start + seconds - 1e-9:
        end = min(position + step, start + seconds)
        clock.tick(end - position)
        last = beat(client, activity, seq=seqs[key], ranges=[(position, end)], session=session)
        assert last.status_code == 200, last.content
        position, seqs[key] = end, seqs[key] + 1
    return last.json()


class TestCompletion:
    def test_genuine_playback_completes_it_at_the_threshold_and_not_before(
        self, lc, learner, activity, clock
    ):
        reply = play(lc, clock, activity, 90)
        assert not reply["completed"] and reply["state"] is None or reply["state"] == "started"
        assert reply["watched_fraction"] == pytest.approx(0.75)
        reply = play(lc, clock, activity, 15, start=90)  # 105 s: still short
        assert not reply["completed"]
        reply = play(lc, clock, activity, 3, start=105)  # 108 s: exactly the threshold
        assert reply["completed"] and reply["state"] == "completed"
        assert ActivityProgress.objects.get(user=learner, activity=activity).state == "completed"
        assert row(learner, activity).completed_at is not None

    def test_just_under_does_not_complete(self, lc, learner, activity, clock):
        reply = play(lc, clock, activity, NEEDED - 0.5)
        assert not reply["completed"]
        assert not ActivityProgress.objects.filter(
            user=learner, activity=activity, state="completed"
        ).exists()

    def test_a_threshold_set_by_the_author_is_respected(self, lc, activity, clock):
        Activity.objects.filter(pk=activity.pk).update(
            config={**activity.config, "completion_threshold": 0.5}
        )
        assert play(lc, clock, activity, 60)["completed"]  # 50% of 120 s

    def test_completing_it_lets_the_lesson_be_completed(self, lc, learner, course, activity, clock):
        _, _, first, second, _ = course
        play(lc, clock, activity, 110)
        response = lc.post(reverse("progress_api:lesson-complete", args=[second.pk]))
        assert response.status_code == 200
        assert LessonCompletion.objects.filter(user=learner, node=second).exists()

    def test_an_unfinished_video_still_blocks_its_lesson(self, lc, course, activity, clock):
        play(lc, clock, activity, 30)
        response = lc.post(reverse("progress_api:lesson-complete", args=[course[3].pk]))
        assert response.status_code == 409

    def test_the_client_cannot_say_it_is_done(self, lc, learner, activity):
        response = beat(
            lc, activity, ranges=[(0, 5)], completed=True, state="completed", completed_at="now"
        )
        assert response.status_code == 200 and response.json()["completed"] is False
        assert row(learner, activity).completed_at is None

    @pytest.mark.parametrize("name", ["activity-complete", "activity-start"])
    def test_there_is_no_mark_as_watched(self, lc, activity, name):
        response = lc.post(reverse(f"progress_api:{name}", args=[activity.pk]))
        if name == "activity-complete":
            assert response.status_code == 400
            assert "completed by watching" in response.json()["detail"]
        assert not ActivityProgress.objects.filter(state="completed").exists()
        assert (
            lc.delete(reverse("progress_api:activity-complete", args=[activity.pk])).status_code
            == 400
        )

    def test_completion_is_permanent_and_later_requests_change_nothing(
        self, lc, learner, activity, clock
    ):
        play(lc, clock, activity, 110)
        before = VideoWatch.objects.values().get(user=learner, activity=activity)
        for i in range(3):
            clock.tick(15)
            response = beat(lc, activity, seq=100 + i, ranges=[(0, 15)], position=3)
            assert response.status_code == 200 and response.json()["completed"]
        after = VideoWatch.objects.values().get(user=learner, activity=activity)
        for field in ("ranges", "credited_seconds", "heartbeats", "last_position", "completed_at"):
            assert after[field] == before[field], field


class TestNoCreditForSkippingOrForging:
    def test_claiming_the_whole_video_in_one_go_earns_only_the_starting_allowance(
        self, lc, learner, activity
    ):
        response = beat(lc, activity, ranges=[(0, 120)], position=120)
        assert response.status_code == 200
        body = response.json()
        assert not body["completed"]
        assert body["accepted_seconds"] == pytest.approx(watch.INITIAL_BUDGET)
        assert row(learner, activity).rejected_seconds == pytest.approx(120 - watch.INITIAL_BUDGET)

    def test_a_flood_of_heartbeats_does_not_make_time_pass(self, lc, learner, activity, clock):
        for seq in range(30):
            beat(lc, activity, seq=seq, ranges=[(seq * 4, seq * 4 + 4)])
        assert row(learner, activity).credited_seconds <= watch.INITIAL_BUDGET + 1e-6

    def test_heartbeats_faster_than_real_time_earn_only_what_real_time_allows(
        self, lc, learner, activity, clock
    ):
        position = 0.0
        for seq in range(20):  # claims 15 s of video every 1 s of real time
            clock.tick(1)
            beat(lc, activity, seq=seq, ranges=[(position, position + 15)])
            position += 15
        got = row(learner, activity).credited_seconds
        assert got <= watch.INITIAL_BUDGET + 20 * watch.TOLERANCE + 1e-6
        assert got < NEEDED

    def test_a_quiet_client_cannot_save_up_unlimited_credit(self, lc, learner, activity, clock):
        beat(lc, activity, seq=0, ranges=[(0, 15)])
        clock.tick(3600)  # an hour of silence
        response = beat(lc, activity, seq=1, ranges=[(15, 120)], position=120)
        assert response.status_code == 200
        credited = row(learner, activity).credited_seconds
        assert credited <= 15 + watch.BUCKET_CAPACITY + 1e-6
        assert not response.json()["completed"]  # 105 s < 108 s

    def test_skipped_sections_get_nothing_and_rewatching_gets_nothing_extra(
        self, lc, learner, activity, clock
    ):
        clock.tick(10)
        beat(lc, activity, seq=0, ranges=[(0, 10)])
        clock.tick(10)
        beat(lc, activity, seq=1, ranges=[(60, 70)])  # jumped ahead: 10–60 never played
        clock.tick(10)
        beat(lc, activity, seq=2, ranges=[(0, 10)], position=10)  # went back to rewatch
        r = row(learner, activity)
        assert r.ranges == [[0.0, 10.0], [60.0, 70.0]]
        assert r.credited_seconds == 20

    def test_when_the_claim_exceeds_the_budget_the_earliest_stretches_win(
        self, lc, learner, activity
    ):
        beat(lc, activity, ranges=[(0, 4), (50, 60), (100, 110)])  # 24 s claimed, 5 s allowed
        r = row(learner, activity)
        assert r.ranges == [[0.0, 4.0], [50.0, 51.0]]
        assert r.rejected_seconds == pytest.approx(19)

    def test_a_forward_seek_claiming_continuity_gets_no_extra(self, lc, learner, activity, clock):
        clock.tick(15)
        beat(lc, activity, seq=0, ranges=[(0, 15)])
        clock.tick(15)
        beat(lc, activity, seq=1, ranges=[(15, 100)], position=100)  # "played" 85 s in 15 s
        assert row(learner, activity).credited_seconds <= 15 + 5 + 15 * 1.1 + 15 + 1e-6

    def test_playing_too_fast_earns_nothing_and_is_noted(self, lc, learner, activity, clock):
        for seq in range(3):
            clock.tick(15)
            beat(lc, activity, seq=seq, ranges=[(seq * 30, seq * 30 + 30)], rate=2.0)
        r = row(learner, activity)
        assert r.credited_seconds == 0 and r.fast_heartbeats == 3
        assert r.needs_review and "too_fast" in r.review_reasons

    def test_a_little_over_the_speed_is_tolerated_but_a_lot_is_not(self, lc, learner, activity):
        assert beat(lc, activity, ranges=[(0, 5)], rate=1.04).json()["accepted_seconds"] == 5
        assert beat(lc, activity, seq=1, ranges=[(5, 10)], rate=1.2).json()["accepted_seconds"] == 0

    def test_a_faster_credited_speed_can_be_allowed_by_the_author(
        self, lc, learner, activity, clock
    ):
        Activity.objects.filter(pk=activity.pk).update(
            config={**activity.config, "max_credited_rate": 2.0}
        )
        hello(lc, activity, seq=0)
        for seq in range(1, 5):  # 30 s of video per 15 s of real time at 2×
            clock.tick(15)
            reply = beat(
                lc, activity, seq=seq, ranges=[((seq - 1) * 30, (seq - 1) * 30 + 30)], rate=2.0
            ).json()
        assert reply["accepted_seconds"] == 30
        assert row(learner, activity).credited_seconds == 120 or reply["completed"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"ranges": "all of it"},
        {"ranges": [[0, 5], "x"]},
        {"ranges": [[-1, 5]]},
        {"ranges": [[5, 5]]},
        {"ranges": [[5, 4]]},
        {"ranges": [[0, "9"]]},
        {"ranges": [[0, None]]},
        {"ranges": [[0, 1e309]]},  # JSON infinity
        {"ranges": [[0, 500]]},  # past the end of a 120 s video
        {"ranges": [[0, 10], [5, 15]]},  # overlapping
        {"ranges": [[20, 30], [0, 10]]},  # unsorted
        {"ranges": [[i, i + 0.5] for i in range(25)]},  # too many
        {"ranges": {"0": 5}},
        {"seq": -1},
        {"seq": 1.5},
        {"seq": True},
        {"seq": "3"},
        {"seq": 10**12},
        {"session_id": "not-a-uuid"},
        {"session_id": None},
        {"session_id": 12},
        {"rate": 0},
        {"rate": -1},
        {"rate": 100},
        {"rate": "fast"},
        {"hidden_seconds": -5},
        {"hidden_seconds": 10**9},
        {"position": -3},
        {"position": "start"},
    ],
)
def test_fabricated_heartbeats_are_refused_and_change_nothing(lc, learner, activity, overrides):
    assert beat(lc, activity, seq=0, ranges=[(0, 5)]).status_code == 200  # a valid start
    before = VideoWatch.objects.values().get(user=learner, activity=activity)
    response = post_raw(lc, activity, **overrides)
    assert response.status_code == 400, response.content
    detail = response.json()["detail"]
    # (non-finite numbers never even reach us: the JSON parser refuses them first)
    assert detail == "That update wasn’t understood." or "JSON parse error" in detail
    after = VideoWatch.objects.values().get(user=learner, activity=activity)
    assert after == before


@pytest.mark.parametrize("body", [[1, 2], "string", 42, None])
def test_a_body_that_is_not_an_object(lc, activity, body):
    response = lc.post(watch_url(activity), json.dumps(body), content_type="application/json")
    assert response.status_code == 400


def test_nan_in_the_body_is_refused(lc, activity):
    response = lc.post(
        watch_url(activity),
        f'{{"session_id": "{S1}", "seq": 0, "ranges": [[0, NaN]]}}',
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not VideoWatch.objects.exists()


class TestReplayAndOrdering:
    def test_a_retried_heartbeat_is_answered_the_same_and_counts_once(
        self, lc, learner, activity, clock
    ):
        hello(lc, activity)
        clock.tick(15)
        first = beat(lc, activity, seq=1, ranges=[(0, 15)]).json()
        clock.tick(15)
        again = beat(lc, activity, seq=1, ranges=[(0, 15)]).json()
        assert again == first
        r = row(learner, activity)
        assert r.heartbeats == 2 and r.credited_seconds == 15  # the hello and one real one

    def test_reusing_a_seq_with_different_content_is_ignored(self, lc, learner, activity, clock):
        hello(lc, activity)
        clock.tick(15)
        beat(lc, activity, seq=1, ranges=[(0, 15)])
        clock.tick(15)
        response = beat(lc, activity, seq=1, ranges=[(60, 75)])
        assert response.status_code == 200 and response.json()["accepted_seconds"] == 15
        assert row(learner, activity).ranges == [[0.0, 15.0]]

    def test_an_older_seq_arriving_late_changes_nothing(self, lc, learner, activity, clock):
        hello(lc, activity)
        clock.tick(15)
        beat(lc, activity, seq=5, ranges=[(0, 15)])
        clock.tick(15)
        response = beat(lc, activity, seq=2, ranges=[(15, 30)])
        assert response.status_code == 200
        r = row(learner, activity)
        assert r.ranges == [[0.0, 15.0]] and r.heartbeats == 2 and r.last_seq == 5

    def test_a_captured_session_replayed_later_earns_nothing_new(
        self, lc, learner, activity, clock
    ):
        play(lc, clock, activity, 30)
        before = row(learner, activity).credited_seconds
        clock.tick(3600)
        for seq in range(2):  # the same two heartbeats, replayed an hour on
            beat(lc, activity, seq=seq, ranges=[(seq * 15, seq * 15 + 15)])
        assert row(learner, activity).credited_seconds == before

    def test_a_new_session_continues_where_the_last_left_off(self, lc, learner, activity, clock):
        play(lc, clock, activity, 30)
        play(lc, clock, activity, 30, start=30, session=S2)
        r = row(learner, activity)
        assert r.credited_seconds == 60 and r.session_id == uuid.UUID(S2)


class TestTwoTabsOrDevices:
    def test_two_sessions_share_one_budget(self, lc, learner, activity, clock):
        beat(lc, activity, seq=0, session=S1, ranges=[(0, 15)])
        beat(lc, activity, seq=0, session=S2, ranges=[(60, 75)])
        assert row(learner, activity).credited_seconds <= watch.INITIAL_BUDGET + 1e-6

    def test_playing_in_two_places_at_once_is_noted_but_never_blocks(
        self, lc, learner, activity, clock
    ):
        for i in range(4):
            clock.tick(5)
            beat(lc, activity, seq=i, session=str(uuid.uuid4()), ranges=[(i * 5, i * 5 + 5)])
        r = row(learner, activity)
        assert r.needs_review and "multiple_sessions" in r.review_reasons
        assert r.credited_seconds == 20  # still credited what real time allowed

    def test_a_fresh_session_after_a_pause_is_not_suspicious(self, lc, learner, activity, clock):
        play(lc, clock, activity, 30)
        clock.tick(600)
        play(lc, clock, activity, 15, start=30, session=S2)
        assert not row(learner, activity).needs_review


class TestUnusualPatternsAreNotedForTrainers:
    def test_asking_for_more_than_real_time_allows_is_noted_not_punished(
        self, lc, learner, activity
    ):
        beat(lc, activity, ranges=[(0, 100)])
        r = row(learner, activity)
        assert r.needs_review and "over_budget" in r.review_reasons
        assert r.credited_seconds == watch.INITIAL_BUDGET  # and what was earned stays earned

    def test_a_video_left_in_the_background_is_noted(self, lc, learner, activity, clock):
        for seq in range(4):
            clock.tick(15)
            beat(lc, activity, seq=seq, ranges=[(seq * 15, seq * 15 + 15)], hidden_seconds=15)
        r = row(learner, activity)
        assert "mostly_hidden" in r.review_reasons
        assert r.hidden_seconds <= 4 * 16

    def test_hidden_time_cannot_exceed_real_time(self, lc, learner, activity, clock):
        clock.tick(15)
        beat(lc, activity, seq=0, ranges=[(0, 15)], hidden_seconds=3000)
        assert row(learner, activity).hidden_seconds <= 1.0

    def test_a_normal_watch_raises_no_flags(self, lc, learner, activity, clock):
        play(lc, clock, activity, 110)
        r = row(learner, activity)
        assert r.completed_at and not r.needs_review and r.review_reasons == []


class TestResumeAndProgress:
    def test_the_state_endpoint_resumes_where_the_learner_stopped(self, lc, activity, clock):
        before = lc.get(watch_url(activity)).json()
        assert before["position"] == 0 and before["watched_fraction"] == 0
        assert before["needed_fraction"] == 0.9 and before["duration"] == DURATION
        play(lc, clock, activity, 45)
        after = lc.get(watch_url(activity)).json()
        assert after["position"] == 45 and after["watched_fraction"] == pytest.approx(0.375)

    def test_course_progress_carries_a_small_summary(self, lc, course, activity, clock):
        play(lc, clock, activity, 45)
        body = lc.get(reverse("progress_api:course", args=[course[1].pk])).json()
        assert body["watch"][str(activity.pk)] == {"watched_fraction": 0.375, "position": 45.0}

    def test_the_summary_never_reveals_review_flags_to_the_learner(self, lc, course, activity):
        beat(lc, activity, ranges=[(0, 100)])
        text = json.dumps(lc.get(reverse("progress_api:course", args=[course[1].pk])).json())
        assert "needs_review" not in text and "over_budget" not in text

    def test_progress_is_per_learner(self, client, make_role_user, course, activity, clock):
        one = make_role_user(Role.Name.LEARNER, username="one", email="one@example.com")
        two = make_role_user(Role.Name.LEARNER, username="two", email="two@example.com")
        client.force_login(one)
        play(client, clock, activity, 45)
        client.force_login(two)
        assert client.get(watch_url(activity)).json()["watched_fraction"] == 0
        play(client, clock, activity, 15, session=S2)
        assert row(one, activity).credited_seconds == 45
        assert row(two, activity).credited_seconds == 15


class TestGuards:
    def test_anonymous(self, client, activity):
        assert client.get(watch_url(activity)).status_code == 403
        assert beat(client, activity, ranges=[(0, 5)]).status_code == 403

    def test_unknown_activity(self, lc):
        assert lc.get(reverse("progress_api:activity-watch", args=[987654])).status_code == 404

    def test_a_draft_cannot_be_recorded_against(self, lc, author, make_role_user, media_dirs):
        asset = ready_asset(author, media_dirs)
        draft = video_course(make_role_user, asset, publish=False, title="Draft")[4]
        assert lc.get(watch_url(draft)).status_code == 404
        assert beat(lc, draft, ranges=[(0, 5)]).status_code == 404

    def test_an_archived_course_stops_recording(self, lc, course, activity):
        assert beat(lc, activity, ranges=[(0, 5)]).status_code == 200
        catalog.archive_course(course[0])
        assert beat(lc, activity, seq=1, ranges=[(5, 10)]).status_code == 404

    def test_other_kinds_of_activity_are_refused(self, lc, course):
        reading = Activity.objects.get(content_node=course[2], activity_type="reading")
        response = beat(lc, reading, ranges=[(0, 5)])
        assert response.status_code == 400 and "isn’t a video" in response.json()["detail"]

    def test_a_video_with_nothing_behind_it_cannot_be_watched(self, lc, course, activity):
        Activity.objects.filter(pk=activity.pk).update(config={"source": "upload"})
        response = beat(lc, activity, ranges=[(0, 5)])
        assert response.status_code == 400 and "can’t be completed yet" in response.json()["detail"]

    def test_a_locked_lesson_records_nothing(
        self, client, learner, author, make_role_user, media_dirs
    ):
        asset = ready_asset(author, media_dirs)
        locked = video_course(make_role_user, asset, order="sequential", title="Seq")[4]
        client.force_login(learner)
        response = beat(client, locked, ranges=[(0, 5)])
        assert response.status_code == 409 and "Finish “First” first" in response.json()["detail"]
        assert client.get(watch_url(locked)).status_code == 409
        assert not VideoWatch.objects.exists()

    def test_the_heartbeat_endpoint_is_rate_limited(self, lc, activity):
        codes = [beat(lc, activity, seq=i, ranges=[]).status_code for i in range(45)]
        assert codes[:40] == [200] * 40
        assert 429 in codes[40:]


class TestYouTube:
    @pytest.fixture
    def youtube(self, course):
        activity = course[4]
        Activity.objects.filter(pk=activity.pk).update(
            config={"source": "youtube", "youtube_url": YT, "completion_threshold": 0.9}
        )
        activity.refresh_from_db()
        return activity

    def test_the_player_must_report_the_length(self, lc, youtube):
        assert beat(lc, youtube, ranges=[(0, 5)]).status_code == 400
        assert beat(lc, youtube, ranges=[(0, 5)], duration=60).status_code == 200

    @pytest.mark.parametrize("duration", [0, -5, "60", None, 10**7, math.inf])
    def test_nonsense_lengths_are_refused(self, lc, youtube, duration):
        assert beat(lc, youtube, ranges=[(0, 5)], duration=duration).status_code == 400

    def test_it_completes_the_same_way_but_is_marked_best_effort(self, lc, learner, youtube, clock):
        beat(lc, youtube, seq=0, ranges=[], duration=60)  # hello
        position = 0.0
        for seq in range(1, 5):
            clock.tick(15)
            reply = beat(
                lc, youtube, seq=seq, ranges=[(position, position + 15)], duration=60
            ).json()
            position += 15
        assert reply["completed"]
        r = row(learner, youtube)
        assert r.fidelity == "best_effort" and r.needs_review and "best_effort" in r.review_reasons

    def test_the_server_keeps_the_first_length_it_was_told(self, lc, learner, youtube, clock):
        beat(lc, youtube, seq=0, ranges=[(0, 5)], duration=600)
        clock.tick(15)
        beat(lc, youtube, seq=1, ranges=[(5, 20)], duration=10)  # a later attempt to shrink it
        r = row(learner, youtube)
        assert r.duration == 600 and not r.completed_at


class TestShortVideos:
    """Found by trying it in a browser: with a big starting allowance, one forged
    request finished a 30-second video. The allowance is small now, and the
    player says hello when playback starts so the server's clock runs from there."""

    @pytest.fixture
    def short(self, course):
        from apps.media_pipeline.models import MediaAsset

        MediaAsset.objects.update(duration_seconds=30.0)
        return course[4]

    def test_one_forged_request_cannot_finish_a_short_video(self, lc, learner, short):
        response = beat(lc, short, seq=0, ranges=[(0, 30)], position=30)
        assert response.status_code == 200
        assert not response.json()["completed"]
        assert row(learner, short).credited_seconds == pytest.approx(watch.INITIAL_BUDGET)

    def test_finishing_costs_about_the_videos_length_in_real_time(self, lc, learner, short, clock):
        hello(lc, short)
        # Forging "the whole video" every few seconds gets only what time allows…
        seq, finished_after = 1, None
        for second in range(1, 41):
            clock.tick(1)
            reply = beat(lc, short, seq=seq, ranges=[(0, 30)], position=30).json()
            seq += 1
            if reply["completed"]:
                finished_after = second
                break
        # …which is the 90% needed (27 s), less the 5 s allowance, at 1.1×: ≥ ~20 s.
        needed_seconds = (0.9 * 30 - watch.INITIAL_BUDGET) / watch.TOLERANCE
        assert finished_after is not None and finished_after >= needed_seconds - 1

    def test_honest_playback_of_a_short_video_finishes_normally(self, lc, learner, short, clock):
        assert play(lc, clock, short, 30)["completed"]
        r = row(learner, short)
        assert not r.needs_review and r.review_reasons == []

    def test_a_long_stretch_reported_all_at_once_is_noted(self, lc, learner, activity, clock):
        hello(lc, activity)
        clock.tick(70)  # a client that sat quiet, then claims a minute in one go
        beat(lc, activity, seq=1, ranges=[(0, 60)], position=60)
        r = row(learner, activity)
        assert r.credited_seconds == 60
        assert r.needs_review and "burst" in r.review_reasons

    def test_honest_heartbeats_are_never_called_bursts(self, lc, learner, activity, clock):
        play(lc, clock, activity, 100)
        assert "burst" not in row(learner, activity).review_reasons


class TestGoogleDrive:
    """Drive's player can't be measured, so the learner confirms — like a reading."""

    @pytest.fixture
    def drive(self, course):
        activity = course[4]
        Activity.objects.filter(pk=activity.pk).update(
            config={
                "source": "drive",
                "drive_url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view",
            }
        )
        activity.refresh_from_db()
        return activity

    def test_the_learner_confirms_it_and_can_take_it_back(self, lc, learner, drive):
        complete = reverse("progress_api:activity-complete", args=[drive.pk])
        assert lc.post(complete).json() == {"state": "completed"}
        assert ActivityProgress.objects.get(user=learner, activity=drive).state == "completed"
        assert lc.delete(complete).json() == {"state": "started"}

    def test_watch_heartbeats_are_refused_for_it(self, lc, drive):
        response = beat(lc, drive, ranges=[(0, 5)], duration=60)
        assert response.status_code == 400
        assert "confirmed by the learner" in response.json()["detail"]
        assert not VideoWatch.objects.exists()

    def test_an_uploaded_video_still_cannot_be_self_confirmed(self, lc, activity):
        response = lc.post(reverse("progress_api:activity-complete", args=[activity.pk]))
        assert response.status_code == 400

    def test_a_confirmed_drive_video_lets_the_lesson_finish(self, lc, drive, course):
        lc.post(reverse("progress_api:activity-complete", args=[drive.pk]))
        response = lc.post(reverse("progress_api:lesson-complete", args=[course[3].pk]))
        assert response.status_code == 200
