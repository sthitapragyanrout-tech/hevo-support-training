"""13 interns at once, plus three videos being converted.

Real processes, one shared Postgres: the web server (Django's own or gunicorn, see LOAD_WEB
it), a media worker, a practice worker and the scheduler. The model is the scripted
`ControlledFake` — its latency, rate limits and timeouts are *synthetic*; everything
else (database locks, the rate gate, queues, ffmpeg, HTTP) is real.

Run it:  DATABASE_URL=postgres://… uv run pytest -m load -s tests/load

Pass criteria, fixed before the first run (see CRITERIA below). Figures are printed;
nothing here is a claim about how the real provider behaves.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import pytest
from django.db import connection
from django.test import Client

from apps.accounts.models import Role
from apps.bot_sim.models import LLMCall, SimSession, SimTurn
from apps.progress.models import ActivityAttempt
from tests.load.driver import Api, Recorder, pct, summary
from tests.media_helpers import HAVE_FFMPEG
from tests.sim_helpers import approved_scenarios, sim_course

BACKEND = Path(__file__).resolve().parent.parent.parent
SESSIONS = 13
# The web server under test: gunicorn (3 workers × 4 threads, as shipped) or Django's dev server.
WEB = os.environ.get("LOAD_WEB", "gunicorn")
VIDEOS = 3

pytestmark = [pytest.mark.load, pytest.mark.worker, pytest.mark.django_db(transaction=True)]

# Written before the first run. A miss is reported, not argued away.
CRITERIA = {
    "all_finish": f"all {SESSIONS} sessions end `finished`, none abandoned or failed",
    "api_p95": "start / send / poll / result: p95 < 500 ms and no 5xx, including during transcodes",
    "no_throttle": "no learner request is refused by the API throttles (HTTP 429)",
    "no_duplicates": "one customer reply and one evaluation per intern turn, one attempt per finished session",
    "videos_ready": "every video becomes ready; the last within 1.5 × (3 × the single-video baseline)",
    "reply_p95": "send → customer reply visible: p95 < 30 s (synthetic model latency)",
}


@pytest.fixture(autouse=True)
def _need_postgres_and_ffmpeg():
    if "postgresql" not in connection.settings_dict["ENGINE"]:
        pytest.skip("the load test needs Postgres (set DATABASE_URL)")
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe are not installed")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stack:
    """web + media worker + practice worker + beat, each its own process group."""

    def __init__(self, tmp: Path, env: dict[str, str]):
        self.tmp, self.env = tmp, env
        self.control = tmp / "control.json"
        self.control.write_text("{}")
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: dict[str, Path] = {}
        self.port = free_port()

    def set_control(self, **values) -> None:
        self.control.write_text(json.dumps(values))

    def _spawn(self, name: str, argv: list[str], ready: bytes, wait: float = 60) -> None:
        log = self.tmp / f"{name}.log"
        process = subprocess.Popen(
            argv, cwd=BACKEND, env=self.env, stdout=open(log, "wb"),
            stderr=subprocess.STDOUT, start_new_session=True,
        )  # fmt: skip
        self.procs[name], self.logs[name] = process, log
        end = time.time() + wait
        while time.time() < end:
            if ready in log.read_bytes():
                return
            if process.poll() is not None:
                break
            time.sleep(0.2)
        pytest.fail(f"{name} did not start:\n{log.read_text()[-2500:]}")

    def start(self, *, media_concurrency=2, sim_concurrency=4) -> None:
        celery = [sys.executable, "-m", "celery", "-A", "config"]
        flags = ["--without-gossip", "--without-mingle", "--without-heartbeat", "-l", "info"]
        if WEB == "runserver":
            web = [sys.executable, "manage.py", "runserver", f"127.0.0.1:{self.port}", "--noreload"]
            ready = b"Starting development server"
        else:
            web = [
                sys.executable,
                "-m",
                "gunicorn",
                "config.wsgi:application",
                "-c",
                "gunicorn.conf.py",
            ]
            ready = b"Listening at"
            self.env["GUNICORN_BIND"] = f"127.0.0.1:{self.port}"
        self._spawn("web", web, ready)
        self._spawn("worker-media", [*celery, "worker", "-Q", "media", "-n", "media@load", "-c", str(media_concurrency), *flags], b" ready.")  # fmt: skip
        self._spawn("worker-sim", [*celery, "worker", "-Q", "sim", "-n", "sim@load", "-c", str(sim_concurrency), "--max-tasks-per-child", "200", "--prefetch-multiplier", "1", *flags], b" ready.")  # fmt: skip
        self._spawn("beat", [*celery, "beat", "-s", str(self.tmp / "beat-schedule"), "-l", "info"], b"beat: Starting")  # fmt: skip
        end = time.time() + 30
        while time.time() < end:
            if self._healthy():
                return
            time.sleep(0.3)
        pytest.fail("the web server never answered")

    def _healthy(self) -> bool:
        import http.client

        try:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            c.request("GET", "/api/v1/auth/session/")
            return c.getresponse().status in (200, 401, 403)
        except OSError:
            return False

    def log_text(self, name: str) -> str:
        return self.logs[name].read_text(errors="replace")

    def stop(self) -> None:
        """Stop every process group and wait until all are gone, so none still holds
        a connection when pytest drops the test database."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for process in self.procs.values():
                try:
                    os.killpg(process.pid, sig)
                except (ProcessLookupError, PermissionError):  # gone, or only zombies left
                    pass
            end = time.time() + (10 if sig == signal.SIGTERM else 5)
            while time.time() < end and any(_group_alive(p.pid) for p in self.procs.values()):
                time.sleep(0.2)
            if not any(_group_alive(p.pid) for p in self.procs.values()):
                break
        for process in self.procs.values():
            process.wait(timeout=5)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):  # EPERM: only zombies are left
        return False
    return True


@pytest.fixture
def make_stack(tmp_path, media_dirs, settings):
    stacks: list[Stack] = []

    def _make(**extra_env: str) -> Stack:
        db = connection.settings_dict
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DATABASE_URL": (
                f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or 'localhost'}"
                f":{db['PORT'] or 5432}/{db['NAME']}"
            ),
            "MEDIA_ROOT": str(media_dirs),
            "CELERY_BROKER_FOLDER": str(settings.CELERY_BROKER_FOLDER),
            "CELERY_TASK_ALWAYS_EAGER": "false",
            "PYTHONUNBUFFERED": "1",
            "SIMBOT_LLM": "fake",
            "SIMBOT_FAKE_CONTROL": str(tmp_path / "control.json"),
            "SIMBOT_RETRY_BACKOFF_SECONDS": "2",
            "MEDIA_MIN_FREE_MB": "256",
            **extra_env,
        }
        stack = Stack(tmp_path, env)
        stacks.append(stack)
        return stack

    yield _make
    for stack in stacks:
        stack.stop()


def heavy_clip(path: Path) -> Path:
    """A minute of 720p fractal footage: it does not compress well, so ffmpeg works hard."""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "mandelbrot=s=1280x720:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
         "-t", "60", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def cookie_for(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies["sessionid"].value


def fmt(v, unit="ms"):
    if v is None:
        return "—"
    return f"{v:,.0f} {unit}" if unit == "ms" else f"{v:,.1f} {unit}"


def line(label, s, unit="ms"):
    return f"  {label:<22} n={s['n']:<4} p50 {fmt(s['p50'], unit):>10}  p95 {fmt(s['p95'], unit):>10}  max {fmt(s['max'], unit):>10}"


def run_load(
    stack: Stack,
    make_role_user,
    tmp_path,
    *,
    with_video: bool,
    faults: dict,
    latency,
    video_delay=0.0,
):
    """Build the data, run the phases, collect the figures. Returns (report lines, checks)."""
    built = sim_course(make_role_user, title="Load course")
    activity = built["activity"]
    approved_scenarios(8)
    learners = [
        make_role_user(Role.Name.LEARNER, username=f"l{i}", email=f"l{i}@e.com")
        for i in range(SESSIONS + 3)
    ]
    baseline_users, main_users = learners[:3], learners[3:]
    trainer = built["author"]
    stack.start()
    port = stack.port

    out: list[str] = []
    checks: list[tuple[str, bool, str]] = []
    cpu = os.cpu_count()
    web_label = (
        "Django development server (one process, threaded)"
        if WEB == "runserver"
        else f"gunicorn, {os.environ.get('WEB_CONCURRENCY', '3')} workers × {os.environ.get('GUNICORN_THREADS', '4')} threads"
    )
    out.append(
        f"machine: {cpu} CPUs · web = {web_label}, media worker ×2 (the allowed maximum), practice worker ×4, beat"
    )
    if video_delay:
        out.append(
            f"DIAGNOSTIC: the three uploads begin {video_delay:g} s after the {SESSIONS} tickets start"
        )
    out.append(
        f"model: scripted fake, synthetic latency {latency[0]}–{latency[1]} s, faults {faults or 'none'}"
    )

    # -- phase 1: one video alone ---------------------------------------------------
    clip = b""
    baseline_video = None
    if with_video:
        clip_path = heavy_clip(tmp_path / "clip60.mp4")
        clip = clip_path.read_bytes()
        out.append(
            f"video: {len(clip) / 1e6:.0f} MB, 60 s, 1280×720 fractal footage (hard to compress) → converted to H.264/AAC"
        )
        stack.set_control(latency=list(latency), customer_turns=6)
        rec0 = Recorder()
        solo = Api(port, cookie_for(trainer), rec0, "trainer").upload_and_wait(clip, "solo.mp4")
        assert solo["ok"], solo
        baseline_video = solo["seconds"]

    # -- phase 2: idle baseline, one ticket at a time, nothing else running ----------------
    idle = Recorder()
    stack.set_control(latency=list(latency), customer_turns=6)
    for user in baseline_users:
        r = Api(port, cookie_for(user), idle, user.username).play_ticket(activity.pk)
        assert r["ok"], r
    idle_stats = {k: summary(idle.ms(k)) for k in ("start", "send", "poll", "result")}

    # -- phase 3: the load -------------------------------------------------------------
    stack.set_control(latency=list(latency), customer_turns=6, **faults)
    rec = Recorder()
    load_before = os.getloadavg()[0]
    barrier = threading.Barrier(SESSIONS + (VIDEOS if with_video else 0))
    results: dict[str, dict] = {}
    t_start = time.time()
    mark = time.perf_counter()

    def learner(user):
        api = Api(port, cookie_for(user), rec, user.username)
        barrier.wait()
        results[user.username] = api.play_ticket(activity.pk)
        connection.close()  # this thread's own database connection (Client login opened it)

    def video(i):
        api = Api(port, cookie_for(trainer), rec, f"video{i}")
        barrier.wait()
        time.sleep(video_delay)
        results[f"video{i}"] = api.upload_and_wait(clip, f"clip{i}.mp4")
        connection.close()

    threads = [threading.Thread(target=learner, args=(u,)) for u in main_users]
    if with_video:
        threads += [threading.Thread(target=video, args=(i,)) for i in range(VIDEOS)]
    for worker in threads:
        worker.start()
    for worker in threads:
        worker.join(timeout=900)
    wall = time.perf_counter() - mark
    load_after = os.getloadavg()[0]
    alive = [w for w in threads if w.is_alive()]

    # -- numbers -----------------------------------------------------------------------
    out.append("")
    out.append("== idle baseline: 3 tickets in a row, nothing else running ==")
    for k in ("start", "send", "poll", "result"):
        out.append(line(k, idle_stats[k]))
    out.append("")
    out.append(
        f"== load: {SESSIONS} tickets at once{' + 3 video conversions' if with_video else ''} — wall clock {wall:.0f} s · 1-min load average {load_before:.1f} → {load_after:.1f} on {cpu} CPUs =="
    )
    load_stats = {k: summary(rec.ms(k, since=t_start)) for k in ("start", "send", "poll", "result")}
    for k in ("start", "send", "poll", "result"):
        out.append(line(k, load_stats[k]))
    if with_video:
        out.append(line("upload (request)", summary(rec.ms("upload", since=t_start))))
        out.append(line("media_poll", summary(rec.ms("media_poll", since=t_start))))
    out.append(
        "  retried once on a fresh connection (the server had closed an idle keep-alive one): "
        f"{len(rec.values('reconnect'))} of {len(rec.samples)} requests"
    )
    out.append(
        "  statuses: " + ", ".join(f"{k}={v}" for k, v in sorted(rec.status_counts().items()))
    )
    out.append(
        "  by label: "
        + "; ".join(
            f"{name}: {dict(sorted(rec.status_counts(name).items()))}"
            for name in ("start", "send", "poll", "result")
        )
    )
    # What the server says the same `start` requests cost (gunicorn's own request timer).
    server_ms = [
        int(m.group(1)) / 1000
        for m in re.finditer(
            r'"POST /api/v1/sim/activities/\d+/sessions/ HTTP/1\.[01]" 201 \d+ (\d+)us',
            stack.log_text("web"),
        )
    ]
    if server_ms and WEB == "gunicorn":
        server_ms = server_ms[-SESSIONS:]  # the 13 simultaneous ones (the baseline came first)
        out.append(
            f"  start as the server timed it (inside the handler): p50 {pct(server_ms, 50):.0f} ms, "
            f"max {max(server_ms):.0f} ms — the client saw p50 {load_stats['start']['p50']:.0f} ms, "
            f"max {load_stats['start']['max']:.0f} ms"
        )
    # Which requests were slow, and were they in flight while an upload was being received?
    uploads = [(x.at, x.at + x.ms / 1000) for x in rec.samples if x.label == "upload"]
    slow_reqs = [
        x
        for x in rec.samples
        if x.at >= t_start and x.ms >= 500 and x.label not in ("upload", "media_poll")
    ]

    def overlaps(x) -> bool:
        end = x.at + x.ms / 1000
        return any(x.at < b and end > a for a, b in uploads)

    inside = [x for x in slow_reqs if overlaps(x)]
    if uploads:
        windows = ", ".join(f"{a - t_start:.1f}–{b - t_start:.1f} s" for a, b in sorted(uploads))
        out.append(
            f"  requests ≥ 500 ms (excluding the uploads themselves): {len(slow_reqs)}; "
            f"{len(inside)} overlapped an upload being received (uploads at {windows} after the start)"
        )
        outside = [x for x in slow_reqs if x not in inside]
        if outside:
            out.append(
                "  slow requests NOT overlapping an upload: "
                + ", ".join(
                    f"{x.label} {x.ms:,.0f} ms at {x.at - t_start:.1f} s" for x in outside[:8]
                )
            )
    reply_wait = rec.values("reply_wait")
    feedback_wait = rec.values("feedback_wait")
    out.append(line("send→reply visible", summary(reply_wait), "s"))
    out.append(line("last reply→feedback", summary(feedback_wait), "s"))
    out.append("  (the two above include the 2 s poll interval the browser also has)")

    ids = [r["session"] for r in results.values() if r.get("session")]
    sessions = list(SimSession.objects.filter(pk__in=ids).order_by("pk"))
    states = Counter(s.state for s in sessions)
    out.append("")
    out.append(
        f"== sessions: {dict(states)} · tickets that returned ok: {sum(1 for u in main_users if results.get(u.username, {}).get('ok'))}/{SESSIONS}"
    )

    # queue delay: enqueued → first model call started (turn level); server reply time
    delays: list[float] = []
    reply_server: list[float] = []
    attempts: Counter[int] = Counter()
    for turn in SimTurn.objects.filter(session_id__in=ids, role="intern").select_related("session"):
        first = LLMCall.objects.filter(turn=turn).order_by("created_at", "id").first()
        if first and turn.job_enqueued_at:
            started = first.created_at.timestamp() - first.latency_ms / 1000
            delays.append(max(0.0, started - turn.job_enqueued_at.timestamp()))
        nxt = SimTurn.objects.filter(session_id=turn.session_id, seq=turn.seq + 1).first()
        if nxt:
            reply_server.append((nxt.at - turn.at).total_seconds())
        attempts[turn.job_attempts] += 1
    out.append(
        line("queue delay", summary(delays), "s") + "   (turn queued → first model call began)"
    )
    out.append(
        line("server reply time", summary(reply_server), "s")
        + "   (reply accepted → customer message committed)"
    )
    out.append(f"  job attempts per intern turn: {dict(sorted(attempts.items()))}")

    calls = Counter(LLMCall.objects.filter(session_id__in=ids).values_list("task", "status"))
    out.append(
        "  model calls (task, status): "
        + ", ".join(f"{t}/{s}={n}" for (t, s), n in sorted(calls.items()))
    )
    rate_limited = sum(n for (_, s), n in calls.items() if s == "rate_limited")
    timeouts = sum(n for (_, s), n in calls.items() if s == "timeout")
    sim_log = stack.log_text("worker-sim")
    gate_waits = len(re.findall(r"LLM rate gate: waiting", sim_log))
    deferred = len(re.findall(r"deferred [\d.]+s by the rate gate", sim_log))
    failed_turns = SimTurn.objects.filter(session_id__in=ids, job_state="failed").count()
    out.append(
        f"  provider 429s: {rate_limited} · timeouts: {timeouts} · gate waits (slept): {gate_waits} · turns deferred by the gate: {deferred} · failed turns: {failed_turns}"
    )

    video_times = []
    if with_video:
        video_times = sorted(
            r["seconds"] for k, r in results.items() if k.startswith("video") and r.get("ok")
        )
        out.append("")
        out.append(
            f"== videos: single-video baseline {baseline_video:.1f} s (upload → ready, nothing else running) =="
        )
        out.append("  under load, upload → ready: " + ", ".join(f"{v:.1f} s" for v in video_times))
        gaps = [video_times[0]] + [
            b - a for a, b in zip(video_times, video_times[1:], strict=False)
        ]
        out.append(
            "  gaps between completions (two media workers: the first two run side by side, the third waits): "
            + ", ".join(f"{g:.1f} s" for g in gaps)
        )

    # -- invariants ---------------------------------------------------------------------
    problems: list[str] = []
    for s in sessions:
        turns = list(s.turns.order_by("seq"))
        if [t.seq for t in turns] != list(range(1, len(turns) + 1)):
            problems.append(f"session {s.pk}: seq gap")
        for t in turns:
            expect = "customer" if t.seq % 2 == 1 else "intern"
            if t.role != expect:
                problems.append(f"session {s.pk}#{t.seq}: role {t.role} at seq {t.seq}")
            if t.role == "intern" and (t.scores is None or t.job_state != "done"):
                problems.append(f"session {s.pk}#{t.seq}: not evaluated/done ({t.job_state})")
    interns = SimTurn.objects.filter(session_id__in=ids, role="intern").count()
    customers_replied = (
        SimTurn.objects.filter(session_id__in=ids, role="customer", seq__gt=1)
        .exclude(action="nudge")
        .count()
    )
    eval_ok = LLMCall.objects.filter(session_id__in=ids, task="evaluate", status="ok").count()
    cust_ok = LLMCall.objects.filter(session_id__in=ids, task="customer", status="ok").count()
    finished = [s for s in sessions if s.state == "finished"]
    attempts_n = ActivityAttempt.objects.filter(
        user_id__in=[s.user_id for s in finished], activity=activity
    ).count()
    per_session_attempts = Counter(
        a
        for a in SimSession.objects.filter(pk__in=ids)
        .exclude(attempt=None)
        .values_list("attempt_id", flat=True)
    )
    out.append("")
    out.append("== invariants ==")
    out.append(
        f"  intern turns {interns} · customer replies {customers_replied} (a closing turn may have none) · evaluate calls ok {eval_ok} · customer calls ok {cust_ok}"
    )
    out.append(
        f"  finished sessions {len(finished)} · attempts recorded {attempts_n} · attempt reused by two sessions: {sum(1 for v in per_session_attempts.values() if v > 1)}"
    )
    if problems:
        out.append("  PROBLEMS: " + "; ".join(problems[:8]))
    else:
        out.append("  no sequence gaps, wrong roles, or unevaluated turns")

    # -- criteria -----------------------------------------------------------------------
    def check(key, ok, detail):
        checks.append((key, ok, detail))

    check("all_finish", len(finished) == SESSIONS and not alive and failed_turns == 0,
          f"{len(finished)}/{SESSIONS} finished, {failed_turns} failed turns, {len(alive)} stuck clients")  # fmt: skip
    slow = {k: v["p95"] for k, v in load_stats.items() if v["p95"] is not None and v["p95"] >= 500}
    bad_5xx = sum(n for s, n in rec.status_counts().items() if s >= 500 or s == 0)
    check(
        "api_p95",
        not slow and bad_5xx == 0,
        f"p95 ≥ 500 ms: {slow or 'none'}; 5xx/connection errors: {bad_5xx}",
    )
    throttled = sum(rec.status_counts(k).get(429, 0) for k in ("start", "send", "poll", "result"))
    check("no_throttle", throttled == 0, f"{throttled} requests got 429")
    check("no_duplicates", not problems and eval_ok == interns and attempts_n == len(finished) and all(v == 1 for v in per_session_attempts.values()),
          f"evaluate calls {eval_ok} vs intern turns {interns}; attempts {attempts_n} vs finished {len(finished)}")  # fmt: skip
    if with_video:
        assert baseline_video is not None
        limit = 1.5 * VIDEOS * baseline_video
        check("videos_ready", len(video_times) == VIDEOS and video_times[-1] <= limit,
              f"{len(video_times)}/{VIDEOS} ready; last at {video_times[-1] if video_times else float('nan'):.1f} s vs limit {limit:.1f} s")  # fmt: skip
    rp95 = pct(reply_wait, 95)
    check(
        "reply_p95",
        rp95 is not None and rp95 < 30,
        f"p95 {rp95 if rp95 is None else round(rp95, 1)} s",
    )

    out.append("")
    out.append("== pass criteria (fixed in advance) ==")
    for key, ok, detail in checks:
        out.append(f"  [{'PASS' if ok else 'MISS'}] {CRITERIA[key]} — {detail}")
    return out, checks


def emit(title: str, lines: list[str], tmp_path: Path) -> None:
    text = "\n".join([f"\n######## {title} ########", *lines, ""])
    print(text)
    report = tmp_path / "load-report.txt"
    report.write_text(text)
    print(f"(report saved to {report})")


def test_13_tickets_with_three_video_conversions(make_stack, make_role_user, tmp_path):
    stack = make_stack()
    lines, checks = run_load(
        stack, make_role_user, tmp_path, with_video=True,
        faults={"rate_limit_rate": 0.05, "timeout_rate": 0.01}, latency=(0.3, 1.5),
    )  # fmt: skip
    emit("13 tickets at once + 3 video conversions", lines, tmp_path)
    missed = [f"{k}: {d}" for k, ok, d in checks if not ok]
    assert not missed, "criteria missed — " + " | ".join(missed)


def test_13_tickets_against_a_tight_rate_limit(make_stack, make_role_user, tmp_path):
    """The shared rate gate under pressure: 90 model calls a minute for ~170 calls."""
    stack = make_stack(SIMBOT_LLM_RPM="90")
    lines, checks = run_load(
        stack, make_role_user, tmp_path, with_video=False,
        faults={"rate_limit_rate": 0.03}, latency=(0.3, 1.0),
    )  # fmt: skip
    emit("13 tickets at once, RPM limit 90", lines, tmp_path)
    log = stack.log_text("worker-sim")
    engaged = len(re.findall(r"rate gate", log))
    print(f"rate gate engaged {engaged} times in the practice worker log")
    missed = [f"{k}: {d}" for k, ok, d in checks if not ok]
    assert engaged > 0, "the limiter never engaged — the test did not exercise it"
    assert not missed, "criteria missed — " + " | ".join(missed)


def test_diagnostic_uploads_begin_after_the_tickets_start(make_stack, make_role_user, tmp_path):
    """Same load, but the three uploads begin 3 s after the 13 tickets have started —
    to see whether the slow `start` in the main run came from the uploads landing at
    the same instant. A diagnostic, not a replacement for the main criteria."""
    stack = make_stack()
    lines, checks = run_load(
        stack, make_role_user, tmp_path, with_video=True,
        faults={"rate_limit_rate": 0.05, "timeout_rate": 0.01}, latency=(0.3, 1.5), video_delay=3.0,
    )  # fmt: skip
    emit("DIAGNOSTIC: uploads 3 s after the tickets start", lines, tmp_path)
    missed = [f"{k}: {d}" for k, ok, d in checks if not ok]
    assert not missed, "criteria missed — " + " | ".join(missed)


def test_diagnostic_what_stalls_during_a_conversion(make_stack, make_role_user, tmp_path):
    """One conversion, no tickets. Three things are timed every 100 ms — an API request
    that needs the database, a bare database commit, and which ffmpeg phase is running —
    to see what the ~2 s stall seen at the end of the encode in the main run is."""
    import psycopg

    built = sim_course(make_role_user, title="Probe course")
    trainer = built["author"]
    learner = make_role_user(Role.Name.LEARNER, username="probe", email="probe@e.com")
    stack = make_stack()
    stack.start()
    clip = heavy_clip(tmp_path / "clip60.mp4").read_bytes()
    db = connection.settings_dict
    raw = psycopg.connect(
        dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"],
        host=db["HOST"] or "localhost", port=db["PORT"] or 5432, autocommit=True,
    )  # fmt: skip
    raw.execute("CREATE TABLE load_probe (t double precision)")

    t0 = time.time()
    stop = threading.Event()
    http_probe: list[tuple[float, float]] = []
    db_probe: list[tuple[float, float]] = []
    phases: list[tuple[float, str]] = []

    def phase_of(ps_text: str) -> str:
        if "-f null" in ps_text:
            return "verify-decode"
        if "libx264" in ps_text and "-movflags" in ps_text:
            return "encode"
        if "-frames:v" in ps_text:
            return "poster"
        if "ffprobe" in ps_text:
            return "probe"
        return "-"

    def http_loop():
        api = Api(stack.port, cookie_for(learner), Recorder(), "probe")
        while not stop.is_set():
            started = time.perf_counter()
            api.call("GET", "/api/v1/auth/session/", "probe")
            http_probe.append((time.time() - t0, (time.perf_counter() - started) * 1000))
            time.sleep(0.1)

    def db_loop():
        while not stop.is_set():
            started = time.perf_counter()
            raw.execute("INSERT INTO load_probe VALUES (%s)", (time.time(),))
            db_probe.append((time.time() - t0, (time.perf_counter() - started) * 1000))
            time.sleep(0.1)

    def phase_loop():
        while not stop.is_set():
            text = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
            lines = [ln for ln in text.splitlines() if "ffmpeg" in ln or "ffprobe" in ln]
            phases.append((time.time() - t0, phase_of(" ".join(lines))))
            time.sleep(0.25)

    threads = [threading.Thread(target=f, daemon=True) for f in (http_loop, db_loop, phase_loop)]
    for th in threads:
        th.start()
    time.sleep(2)
    result = Api(stack.port, cookie_for(trainer), Recorder(), "trainer").upload_and_wait(
        clip, "probe.mp4"
    )
    time.sleep(2)
    stop.set()
    for th in threads:
        th.join(timeout=5)

    def spans():
        out, last, start = [], None, 0.0
        for at, name in phases:
            if name != last:
                if last is not None:
                    out.append((last, start, at))
                last, start = name, at
        if last is not None:
            out.append((last, start, phases[-1][0]))
        return out

    lines = ["", "######## DIAGNOSTIC: what stalls during one conversion ########"]
    lines.append(f"conversion finished: {result['ok']} in {result.get('seconds') or 0:.1f} s")
    lines.append("ffmpeg phases (seconds from the start of the probe): " + "; ".join(
        f"{n} {a:.1f}–{b:.1f}" for n, a, b in spans() if n != "-"))  # fmt: skip
    for name, series in (
        ("API request needing the database", http_probe),
        ("database commit", db_probe),
    ):
        values = [ms for _, ms in series]
        slow_ones = [(at, ms) for at, ms in series if ms >= 300]
        lines.append(
            f"{name}: n={len(values)} p50 {pct(values, 50):.0f} ms p95 {pct(values, 95):.0f} ms "
            f"max {max(values):.0f} ms; ≥300 ms: {len(slow_ones)}"
            + (" at " + ", ".join(f"{at:.1f}s ({ms:,.0f} ms)" for at, ms in slow_ones[:10]) if slow_ones else "")
        )  # fmt: skip
    raw.close()
    text = "\n".join(lines)
    print(text)
    (tmp_path / "diagnostic.txt").write_text(text)
    assert result["ok"]


def test_diagnostic_commit_latency_while_three_uploads_arrive(make_stack, make_role_user, tmp_path):
    """No tickets: three 109 MB uploads arrive together while a bare database commit and
    an API request that writes are timed every 50 ms. Is it the disk burst that slows
    writes (and so the write-heavy `start`)?"""
    import psycopg

    built = sim_course(make_role_user, title="Probe course 2")
    approved_scenarios(3)
    trainer = built["author"]
    stack = make_stack()
    stack.start()
    clip = heavy_clip(tmp_path / "clip60.mp4").read_bytes()
    db = connection.settings_dict
    raw = psycopg.connect(
        dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"],
        host=db["HOST"] or "localhost", port=db["PORT"] or 5432, autocommit=True,
    )  # fmt: skip
    raw.execute("CREATE TABLE load_probe2 (t double precision)")
    t0 = time.time()
    stop = threading.Event()
    commits: list[tuple[float, float]] = []

    def commit_loop():
        while not stop.is_set():
            started = time.perf_counter()
            raw.execute("INSERT INTO load_probe2 VALUES (%s)", (time.time(),))
            commits.append((time.time() - t0, (time.perf_counter() - started) * 1000))
            time.sleep(0.05)

    prober = threading.Thread(target=commit_loop, daemon=True)
    prober.start()
    time.sleep(2)
    mark = time.time() - t0
    barrier = threading.Barrier(3)
    windows: list[tuple[float, float]] = []

    def upload(i):
        api = Api(stack.port, cookie_for(trainer), Recorder(), f"v{i}")
        barrier.wait()
        a = time.time() - t0
        boundary = "----probe" + uuid.uuid4().hex
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="p{i}.mp4"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        api.call(
            "POST", "/api/v1/authoring/media/", "upload",
            raw=head + clip + f"\r\n--{boundary}--\r\n".encode(),
            content_type=f"multipart/form-data; boundary={boundary}",
        )  # fmt: skip
        windows.append((a, time.time() - t0))

    import uuid

    uploads = [threading.Thread(target=upload, args=(i,)) for i in range(3)]
    for th in uploads:
        th.start()
    for th in uploads:
        th.join(timeout=120)
    time.sleep(2)
    stop.set()
    prober.join(timeout=5)
    raw.close()

    inside = [ms for at, ms in commits if any(a <= at <= b for a, b in windows)]
    outside = [ms for at, ms in commits if not any(a <= at <= b for a, b in windows)]
    slow = [(at, ms) for at, ms in commits if ms >= 100]
    lines = ["", "######## DIAGNOSTIC: commit latency while three uploads arrive ########"]
    lines.append(
        "upload windows (s): " + ", ".join(f"{a:.1f}–{b:.1f}" for a, b in sorted(windows))
        + f"   (probe began {mark:.1f} s before the uploads)"
    )  # fmt: skip
    for name, values in (("outside the uploads", outside), ("during the uploads", inside)):
        if values:
            lines.append(
                f"database commit {name}: n={len(values)} p50 {pct(values, 50):.0f} ms "
                f"p95 {pct(values, 95):.0f} ms max {max(values):.0f} ms"
            )
    lines.append(
        f"commits ≥ 100 ms: {len(slow)}"
        + (" at " + ", ".join(f"{at:.1f}s ({ms:,.0f} ms)" for at, ms in slow[:10]) if slow else "")
    )  # fmt: skip
    text = "\n".join(lines)
    print(text)
    (tmp_path / "diagnostic2.txt").write_text(text)
