"""What the browser does, without the browser: an HTTP client that logs in with a
session cookie, plays a practice ticket (start → reply → poll → result) at human
pace, uploads a video and waits for it. Every request is timed."""

from __future__ import annotations

import http.client
import json
import random
import string
import threading
import time
import uuid
from dataclasses import dataclass

REPLIES = [
    "Hi! Thanks for reaching out. To connect MySQL, open Sources → New Source → MySQL and enter the host, port, database and a user with SELECT and replication privileges. Steps: https://docs.hevodata.com/sources/dbfs/databases/mysql/",
    "Sorry for the trouble. Please allow Hevo's IP addresses on your firewall first, then re-run the connection test. The list is here: https://docs.hevodata.com/getting-started/connection-options/whitelist-hevo-ips/",
    "Happy to help further. Could you tell me which region your workspace is in? The IP list differs per region, and I'll point you to the right one. Docs: https://docs.hevodata.com/",
    "Thanks for the detail. The pipeline's Overview tab shows the latest ingestion status and any errors, and you can pause and resume the pipeline from there. https://docs.hevodata.com/pipelines/",
    "Understood. After you grant the privileges, test the connection again; if it still fails, send me the exact error text and I'll look into it right away.",
    "Glad that helped! If anything else comes up, just reply here. Reference: https://docs.hevodata.com/",
]


@dataclass
class Sample:
    label: str
    status: int
    ms: float
    at: float  # wall clock, seconds
    who: str


class Recorder:
    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self.events: list[tuple[str, str, float]] = []  # (kind, who, value)
        self._lock = threading.Lock()

    def add(self, sample: Sample) -> None:
        with self._lock:
            self.samples.append(sample)

    def event(self, kind: str, who: str, value: float) -> None:
        with self._lock:
            self.events.append((kind, who, value))

    def values(self, kind: str) -> list[float]:
        return [v for k, _, v in self.events if k == kind]

    def ms(self, label: str, *, since: float = 0.0, ok_only: bool = True) -> list[float]:
        return [
            s.ms
            for s in self.samples
            if s.label == label and s.at >= since and (not ok_only or 200 <= s.status < 300)
        ]

    def status_counts(self, label: str | None = None) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in self.samples:
            if label is None or s.label == label:
                out[s.status] = out.get(s.status, 0) + 1
        return out


def pct(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))
    return ordered[int(rank) - 1]


def summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "p50": pct(values, 50),
        "p95": pct(values, 95),
        "max": max(values) if values else None,
    }


class Api:
    def __init__(self, port: int, session_id: str, recorder: Recorder, who: str) -> None:
        self.port, self.recorder, self.who = port, recorder, who
        self.csrf = "".join(random.choices(string.ascii_letters + string.digits, k=64))
        self.cookie = f"sessionid={session_id}; csrftoken={self.csrf}"
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        self.reused = False  # has this connection already served a request?

    def call(self, method, path, label, body=None, *, raw=None, content_type=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Cookie": self.cookie, "X-CSRFToken": self.csrf}
        if data is not None:
            headers["Content-Type"] = content_type or "application/json"
        started, wall = time.perf_counter(), time.time()
        status, payload = 0, None
        for attempt in (1, 2):
            try:
                self.conn.request(method, path, body=data, headers=headers)
                response = self.conn.getresponse()
                text = response.read()
                status = response.status
                self.reused = True
                try:
                    payload = json.loads(text) if text else None
                except ValueError:
                    payload = None
                break
            except (OSError, http.client.HTTPException) as exc:
                dropped = isinstance(
                    exc,
                    (
                        http.client.RemoteDisconnected,
                        ConnectionResetError,
                        BrokenPipeError,
                        http.client.CannotSendRequest,
                    ),
                )
                was_reused = self.reused
                self.conn.close()
                self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
                self.reused = False
                # The server closed an idle keep-alive connection just as we reused it:
                # a browser silently retries once on a fresh connection, so do the same
                # (and count it). Replies are idempotent on client_id, so this is safe.
                if attempt == 1 and was_reused and dropped:
                    self.recorder.event("reconnect", self.who, 1.0)
                    started, wall = time.perf_counter(), time.time()
                    continue
                break
        ms = (time.perf_counter() - started) * 1000
        self.recorder.add(Sample(label, status, ms, wall, self.who))
        return status, payload

    # -- a practice ticket ------------------------------------------------------

    def play_ticket(self, activity_id: int, *, think=(1.0, 3.0), poll=2.0, deadline=420.0):
        """Returns {'session': id, 'ok': bool, 'why': str}."""
        rng = random.Random(self.who)
        stop = time.time() + deadline
        status, body = self.call(
            "POST", f"/api/v1/sim/activities/{activity_id}/sessions/", "start", {}
        )
        if status not in (200, 201) or not body:
            return {"session": None, "ok": False, "why": f"start answered {status}"}
        sid = body["id"]
        replies = 0
        while time.time() < stop:
            state = body["state"]
            if state in ("finished", "abandoned"):
                break
            if state == "open" and body["can_reply"] and replies < body["max_exchanges"]:
                time.sleep(rng.uniform(*think))
                text = REPLIES[replies % len(REPLIES)]
                status, _ = self.call(
                    "POST", f"/api/v1/sim/sessions/{sid}/messages/", "send",
                    {"text": text, "client_id": str(uuid.uuid4())},
                )  # fmt: skip
                if status not in (200, 202):
                    time.sleep(poll)
                    status, body = self.call("GET", f"/api/v1/sim/sessions/{sid}/", "poll")
                    continue
                replies += 1
                sent_at = time.perf_counter()
                # Poll the way the window does until the customer answers.
                while time.time() < stop:
                    time.sleep(poll + rng.uniform(0, 0.3))
                    status, body = self.call("GET", f"/api/v1/sim/sessions/{sid}/", "poll")
                    if status == 200 and body and (body["can_reply"] or body["state"] != "open"):
                        self.recorder.event("reply_wait", self.who, time.perf_counter() - sent_at)
                        break
                continue
            if state == "finishing":
                waiting_since = time.perf_counter()
                while time.time() < stop:
                    time.sleep(poll + rng.uniform(0, 0.3))
                    status, body = self.call("GET", f"/api/v1/sim/sessions/{sid}/", "poll")
                    if status == 200 and body and body["state"] != "finishing":
                        self.recorder.event(
                            "feedback_wait", self.who, time.perf_counter() - waiting_since
                        )
                        break
                continue
            time.sleep(poll)
            status, body = self.call("GET", f"/api/v1/sim/sessions/{sid}/", "poll")
            if status != 200 or not body:
                body = body or {"state": "open", "can_reply": False, "max_exchanges": 6}
        if body["state"] != "finished":
            return {"session": sid, "ok": False, "why": f"ended as {body['state']}"}
        status, result = self.call("GET", f"/api/v1/sim/sessions/{sid}/result/", "result")
        ok = status == 200
        return {"session": sid, "ok": ok, "why": "" if ok else f"result answered {status}"}

    # -- a video ----------------------------------------------------------------

    def upload_and_wait(self, clip: bytes, name: str, *, deadline=600.0):
        """Upload, then poll until the converted video is ready. Returns seconds."""
        boundary = "----load" + uuid.uuid4().hex
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        raw = head + clip + f"\r\n--{boundary}--\r\n".encode()
        started = time.perf_counter()
        status, body = self.call(
            "POST", "/api/v1/authoring/media/", "upload", raw=raw,
            content_type=f"multipart/form-data; boundary={boundary}",
        )  # fmt: skip
        if status != 201 or not body:
            return {"ok": False, "why": f"upload answered {status}", "seconds": None, "id": None}
        accepted = time.perf_counter() - started
        end = time.time() + deadline
        while time.time() < end:
            time.sleep(1.0)
            status, body = self.call("GET", f"/api/v1/authoring/media/{body['id']}/", "media_poll")
            if status == 200 and body and body["status"] == "ready":
                return {
                    "ok": True,
                    "why": "",
                    "seconds": time.perf_counter() - started,
                    "accepted": accepted,
                    "id": body["id"],
                }
            if status == 200 and body and body["status"] == "failed":
                return {
                    "ok": False,
                    "why": body.get("error", "failed"),
                    "seconds": None,
                    "id": body["id"],
                }
        return {
            "ok": False,
            "why": "not ready in time",
            "seconds": None,
            "id": body and body.get("id"),
        }
