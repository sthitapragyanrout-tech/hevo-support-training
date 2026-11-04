"""The two hardest claims about verified watching, tested hardest:

  1. For *any* sequence of hostile heartbeats, credited time never exceeds what
     real time allows, and never covers anything that wasn't claimed.
  2. Simultaneous requests (several tabs, racing retries) can't double-count or
     lose an update.

(2) needs real database transactions, so it runs on Postgres only.
"""

import random
import threading
import uuid

import pytest
from django.db import connection, connections
from django.test import Client

from apps.accounts.models import Role
from apps.progress import services, watch, watching
from apps.progress.models import VideoWatch
from tests.media_helpers import ready_asset, video_course
from tests.test_watch_api import DURATION, Clock


@pytest.fixture
def setup(make_role_user, media_dirs):
    author = make_role_user(Role.Name.TRAINER, username="author", email="author@example.com")
    learner = make_role_user(Role.Name.LEARNER, username="lena", email="lena@example.com")
    asset = ready_asset(author, media_dirs)
    activity = video_course(make_role_user, asset, order="free")[4]
    return learner, activity


@pytest.mark.django_db
class TestHostileSequences:
    @pytest.mark.parametrize("seed", range(25))
    def test_credit_never_exceeds_real_time_or_the_claims(self, seed, setup, monkeypatch):
        learner, activity = setup
        clock = Clock()
        monkeypatch.setattr(watching, "_now", clock)
        rng = random.Random(seed)
        sessions = [str(uuid.uuid4()) for _ in range(3)]
        seqs = dict.fromkeys(sessions, 0)
        started_at = None
        claimed: list[watch.Interval] = []
        last_credit = 0.0

        for _ in range(60):
            clock.tick(rng.choice([0, 0, 0.2, 1, 5, 15, 15, 30, 200, 4000]))
            session = rng.choice(sessions)
            if rng.random() < 0.15:  # replay or reorder
                seqs[session] = max(seqs[session] - rng.randint(0, 3), 0)
            seqs[session] += 1
            ranges, cursor = [], 0.0
            for _ in range(rng.randint(0, 5)):
                start = cursor + rng.uniform(0, 40)
                end = start + rng.uniform(0.2, 60)
                if end > DURATION:
                    break
                ranges.append([round(start, 3), round(end, 3)])
                cursor = end
            payload = {
                "session_id": session,
                "seq": seqs[session],
                "position": rng.uniform(0, DURATION),
                "rate": rng.choice([1, 1, 1, 1.04, 1.5, 2, 5]),
                "hidden_seconds": rng.choice([0, 0, 3, 15, 500]),
                "ranges": ranges,
            }
            if rng.random() < 0.1:  # hostile junk now and then
                payload["ranges"] = rng.choice([[[5, 1]], [[0, 9999]], "x", [[0, 1], [0, 1]]])
            try:
                watching.record_watch(learner, activity.pk, payload)
            except services.ProgressError:
                continue
            if started_at is None:
                started_at = clock.now
            if isinstance(payload["ranges"], list):
                claimed = watch.merge([*claimed, *map(tuple, payload["ranges"])])

            r = VideoWatch.objects.get(user=learner, activity=activity)
            credited = watch.from_lists(r.ranges)
            elapsed = (clock.now - started_at).total_seconds()
            ceiling = watch.INITIAL_BUDGET + elapsed * 1.0 * watch.TOLERANCE
            assert r.credited_seconds == pytest.approx(watch.measure(credited))
            assert r.credited_seconds <= ceiling + 1e-6, (seed, r.credited_seconds, ceiling)
            assert r.credited_seconds >= last_credit - 1e-9, "credit must never be taken back"
            assert not watch.subtract(credited, claimed), "credited what nobody claimed"
            assert all(0 <= s < e <= DURATION for s, e in credited)
            assert credited == watch.merge(credited)
            last_credit = r.credited_seconds


def _post(user, activity, payload, results, index):
    try:
        client = Client()
        client.force_login(user)
        import json

        response = client.post(
            f"/api/v1/progress/activities/{activity.pk}/watch/",
            json.dumps(payload),
            content_type="application/json",
        )
        results[index] = (response.status_code, response.json())
    finally:
        connections.close_all()


def _fire(user, activity, payloads):
    results = [None] * len(payloads)
    gate = threading.Barrier(len(payloads))

    def go(i):
        gate.wait()
        _post(user, activity, payloads[i], results, i)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(len(payloads))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


@pytest.mark.django_db(transaction=True)
class TestRealConcurrency:
    @pytest.fixture(autouse=True)
    def _postgres(self):
        if "postgresql" not in connection.settings_dict["ENGINE"]:
            pytest.skip("row locking only exists on Postgres (set DATABASE_URL)")

    def test_simultaneous_tabs_share_one_budget_and_no_update_is_lost(self, setup):
        learner, activity = setup
        n = 8
        payloads = [
            {
                "session_id": str(uuid.uuid4()),
                "seq": 0,
                "position": i * 15 + 15,
                "rate": 1,
                "hidden_seconds": 0,
                "ranges": [[i * 15, i * 15 + 15]],
            }
            for i in range(n)
        ]
        results = _fire(learner, activity, payloads)
        assert all(r and r[0] == 200 for r in results), results
        r = VideoWatch.objects.get(user=learner, activity=activity)
        assert r.heartbeats == n, "a heartbeat was lost or applied twice"
        # 8 tabs each claimed a different 15 s (120 s in all) at the same instant:
        # the bucket allows the starting allowance plus the blink of real time.
        assert r.credited_seconds <= watch.INITIAL_BUDGET + 5
        assert r.rejected_seconds >= 120 - watch.INITIAL_BUDGET - 5 - 1e-6
        assert "multiple_sessions" in r.review_reasons

    def test_the_same_heartbeat_sent_five_times_at_once_counts_once(self, setup):
        learner, activity = setup
        payload = {
            "session_id": str(uuid.uuid4()),
            "seq": 3,
            "position": 15,
            "rate": 1,
            "hidden_seconds": 0,
            "ranges": [[0, 15]],
        }
        results = _fire(learner, activity, [payload] * 5)
        assert all(r and r[0] == 200 for r in results), results
        r = VideoWatch.objects.get(user=learner, activity=activity)
        # a first heartbeat earns only the starting allowance, once, however many copies arrive
        assert r.heartbeats == 1 and r.credited_seconds == watch.INITIAL_BUDGET
        assert all(x[1] == results[0][1] for x in results), "retries should get the same answer"

    def test_a_completion_race_completes_exactly_once(self, setup):
        learner, activity = setup
        VideoWatch.objects.create(
            user=learner,
            activity=activity,
            duration=DURATION,
            ranges=[[0.0, 100.0]],
            credited_seconds=100.0,
            budget=90.0,
            budget_at=watching._now(),
        )
        payloads = [
            {
                "session_id": str(uuid.uuid4()),
                "seq": 0,
                "position": 120,
                "rate": 1,
                "hidden_seconds": 0,
                "ranges": [[100, 120]],
            }
            for _ in range(4)
        ]
        results = _fire(learner, activity, payloads)
        assert all(r and r[0] == 200 for r in results), results
        from apps.progress.models import ActivityProgress

        assert ActivityProgress.objects.filter(user=learner, activity=activity).count() == 1
        assert VideoWatch.objects.get(user=learner, activity=activity).completed_at is not None
