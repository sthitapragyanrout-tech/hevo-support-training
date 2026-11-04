"""A real simulation worker process, a real broker folder, a shared database — and a
worker that is killed in the middle of a turn. Whatever happens, there is exactly
one customer reply, one evaluation, one attempt.

Needs Postgres (a second process must see the data); skipped otherwise.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from django.db import connection

from apps.accounts.models import Role
from apps.bot_sim import services
from apps.bot_sim.models import LLMCall, SimSession, SimTurn
from apps.progress.models import ActivityAttempt
from tests.sim_helpers import GOOD, approved_scenarios, sim_course

BACKEND = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.worker, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _need_postgres():
    if "postgresql" not in connection.settings_dict["ENGINE"]:
        pytest.skip("real-worker tests need Postgres (set DATABASE_URL)")


class Rig:
    def __init__(self, tmp, media, broker, env):
        self.tmp, self.media, self.broker, self.env = tmp, media, broker, env
        self.control = tmp / "control.json"
        self.workers: list[subprocess.Popen] = []
        self.logs: list[Path] = []
        self.control.write_text("{}")

    def set_control(self, **values):
        self.control.write_text(json.dumps(values))

    def start_worker(self):
        log = self.tmp / f"sim-worker-{len(self.workers)}.log"
        process = subprocess.Popen(
            [sys.executable, "-m", "celery", "-A", "config", "worker", "-P", "solo", "-Q", "sim",
             "-n", f"sim{len(self.workers)}@test", "-l", "info",
             "--without-gossip", "--without-mingle", "--without-heartbeat"],
            cwd=BACKEND, env=self.env, stdout=open(log, "wb"), stderr=subprocess.STDOUT,
        )  # fmt: skip
        self.workers.append(process)
        self.logs.append(log)
        deadline = time.time() + 40
        while time.time() < deadline:
            if b" ready." in log.read_bytes():
                return process
            if process.poll() is not None:
                break
            time.sleep(0.2)
        pytest.fail(f"worker did not start:\n{log.read_text()[-2000:]}")

    def manage(self, *args):
        done = subprocess.run(
            [sys.executable, "manage.py", "process_sim", *args],
            cwd=BACKEND, env=self.env, capture_output=True, text=True, timeout=60,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr[-1500:]
        return done.stdout.strip()

    def wait(self, check, what, timeout=45):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.25)
        tails = "\n---\n".join(log.read_text()[-1200:] for log in self.logs)
        pytest.fail(f"timed out waiting for {what}\n{tails}")

    def stop_all(self):
        for process in self.workers:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture
def rig(tmp_path, media_dirs, settings, monkeypatch):
    db = connection.settings_dict
    broker = Path(settings.CELERY_BROKER_FOLDER)
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_URL": (
            f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or 'localhost'}"
            f":{db['PORT'] or 5432}/{db['NAME']}"
        ),
        "MEDIA_ROOT": str(media_dirs),
        "CELERY_BROKER_FOLDER": str(broker),
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "SIMBOT_LLM": "fake",
        "SIMBOT_FAKE_CONTROL": str(tmp_path / "control.json"),
        "SIMBOT_LEASE_SECONDS": "3",
        "SIMBOT_RETRY_BACKOFF_SECONDS": "0",
        "SIMBOT_LLM_CALL_ATTEMPTS": "1",
    }
    # The test process only prepares data and inspects it; the worker does the work.
    monkeypatch.setattr(services, "enqueue_turn", lambda *a, **k: True)
    monkeypatch.setattr(services, "enqueue_finalize", lambda *a, **k: True)
    rig = Rig(tmp_path, media_dirs, broker, env)
    yield rig
    rig.stop_all()


@pytest.fixture
def learner_and_activity(make_role_user):
    built = sim_course(make_role_user)
    approved_scenarios(3)
    learner = make_role_user(Role.Name.LEARNER, username="lena", email="lena@e.com")
    return learner, built["activity"]


def reply(learner, session, text=GOOD):
    turn, _ = services.submit_reply(learner, session.pk, text, uuid.uuid4())
    return turn


def customers(session_id):
    return SimTurn.objects.filter(session_id=session_id, role="customer").count()


def calls(task):
    return LLMCall.objects.filter(task=task, status="ok").count()


class TestRealWorker:
    def test_a_reply_is_evaluated_and_answered(self, rig, learner_and_activity):
        learner, activity = learner_and_activity
        session = services.start(learner, activity.pk)
        turn = reply(learner, session)
        rig.start_worker()
        assert rig.manage("--enqueue-turn", str(turn.pk)) == "queued"
        rig.wait(lambda: customers(session.pk) == 2, "the customer's reply")
        done = SimTurn.objects.get(pk=turn.pk)
        assert done.scores and done.job_state == "done"
        assert (calls("evaluate"), calls("customer")) == (1, 1)

    def test_a_worker_killed_mid_turn_leaves_exactly_one_reply(self, rig, learner_and_activity):
        learner, activity = learner_and_activity
        session = services.start(learner, activity.pk)
        turn = reply(learner, session)
        marker = rig.tmp / "hung"
        rig.set_control(hang={"task": "customer", "seconds": 60, "marker": str(marker)})
        first = rig.start_worker()
        rig.manage("--enqueue-turn", str(turn.pk))
        rig.wait(marker.exists, "the worker to be inside the customer call")

        first.send_signal(signal.SIGKILL)  # no goodbye
        first.wait(timeout=10)
        stuck = SimTurn.objects.get(pk=turn.pk)
        assert stuck.scores is not None  # the evaluation had already landed…
        assert (
            customers(session.pk) == 1 and stuck.job_lease_expires_at is not None
        )  # …the reply hadn't

        rig.set_control()  # the next worker is not slowed down
        time.sleep(4)  # let the dead worker's 3-second claim expire
        rig.start_worker()  # recovers on start: re-queues the turn
        rig.wait(lambda: customers(session.pk) == 2, "the replacement worker's reply")
        time.sleep(1.5)
        assert customers(session.pk) == 2  # still exactly one reply
        assert (calls("evaluate"), calls("customer")) == (
            1,
            1,
        )  # nothing evaluated twice; the killed call never finished
        assert SimTurn.objects.get(pk=turn.pk).job_state == "done"

    def test_the_same_message_delivered_twice_is_worked_on_once(self, rig, learner_and_activity):
        learner, activity = learner_and_activity
        session = services.start(learner, activity.pk)
        turn = reply(learner, session)
        rig.set_control(latency=[0.5, 0.6])
        rig.manage("--enqueue-turn", str(turn.pk))
        rig.manage("--enqueue-turn", str(turn.pk))
        rig.start_worker()
        rig.wait(lambda: customers(session.pk) == 2, "the reply")
        time.sleep(2)  # the duplicate is consumed too
        assert customers(session.pk) == 2 and (calls("evaluate"), calls("customer")) == (1, 1)

    def test_a_worker_killed_while_finalising_still_gives_one_attempt(
        self, rig, learner_and_activity
    ):
        learner, activity = learner_and_activity
        session = services.start(learner, activity.pk)
        # two replies, answered and scored, by the worker; then ask to finish
        rig.start_worker()
        for _ in range(2):
            turn = reply(learner, session)
            rig.manage("--enqueue-turn", str(turn.pk))
            target = customers(session.pk) + 1
            rig.wait(lambda target=target: customers(session.pk) == target, "a customer reply")
        marker = rig.tmp / "hung-narrative"
        rig.set_control(hang={"task": "narrative", "seconds": 60, "marker": str(marker)})
        services.finish(learner, session.pk)
        rig.manage("--enqueue-finalize", str(session.pk))
        rig.wait(marker.exists, "the worker to be writing the feedback")
        rig.workers[0].send_signal(signal.SIGKILL)
        rig.workers[0].wait(timeout=10)
        assert ActivityAttempt.objects.count() == 0
        assert SimSession.objects.get(pk=session.pk).state == "finishing"

        rig.set_control()
        time.sleep(4)  # the dead worker's 3-second claim must expire first
        rig.start_worker()  # its start-up recovery notices the unfinished session
        rig.wait(lambda: SimSession.objects.get(pk=session.pk).state == "finished", "the result")
        assert ActivityAttempt.objects.count() == 1
        assert SimSession.objects.get(pk=session.pk).result["exchanges"] == 2

    def test_a_polite_shutdown_lets_the_current_turn_finish(self, rig, learner_and_activity):
        learner, activity = learner_and_activity
        session = services.start(learner, activity.pk)
        turn = reply(learner, session)
        marker = rig.tmp / "slow"
        rig.set_control(hang={"task": "customer", "seconds": 3, "marker": str(marker)})
        worker = rig.start_worker()
        rig.manage("--enqueue-turn", str(turn.pk))
        rig.wait(marker.exists, "the turn to be under way")
        worker.send_signal(signal.SIGTERM)
        assert worker.wait(timeout=60) == 0
        assert customers(session.pk) == 2 and SimTurn.objects.get(pk=turn.pk).job_state == "done"
