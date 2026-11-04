"""Shared builders for the practice-ticket tests."""

from __future__ import annotations

import json

from django.urls import reverse

from apps.accounts.models import Role
from apps.bot_sim import services
from apps.bot_sim.models import Scenario, SimSession, SimTurn
from apps.bot_sim.seed_data import SAMPLE_SCENARIOS
from apps.catalog import services as catalog
from apps.catalog.models import Activity

GOOD = (
    "Hi! Open Sources → New Source → MySQL, enter the host, port, database and a user with "
    "SELECT and replication privileges, and allow Hevo's IPs on your firewall. "
    "Steps: https://docs.hevodata.com/sources/dbfs/databases/mysql/"
)


def approved_scenarios(n: int = 3, **overrides) -> list[Scenario]:
    out = []
    for i in range(n):
        data = dict(SAMPLE_SCENARIOS[i % len(SAMPLE_SCENARIOS)])
        data["issue_summary"] = f"{data['issue_summary']} (#{i})"
        data.update(overrides)
        out.append(Scenario.objects.create(status=Scenario.Status.APPROVED, source="seed", **data))
    return out


def sim_course(
    make_role_user,
    *,
    order: str = "free",
    max_attempts: int = 3,
    config: dict | None = None,
    publish: bool = True,
    title: str = "Practice course",
):
    """A course whose second lesson holds a practice ticket (and whose first lesson
    holds a required reading, so a course that goes in order locks the ticket)."""
    author = make_role_user(Role.Name.TRAINER, username=f"a-{title}", email=f"a-{title}@e.com")
    admin = make_role_user(Role.Name.ADMIN, username=f"adm-{title}", email=f"adm-{title}@e.com")
    course = catalog.create_course(title=title, user=author)
    version = catalog.open_version(course)
    assert version is not None and version.root_node is not None
    module = catalog.add_node(version.root_node, title="Module")
    first = catalog.add_node(module, title="First")
    Activity.objects.create(
        content_node=first,
        activity_type="reading",
        title="Read",
        config={"source_url": "https://x.io"},
    )
    second = catalog.add_node(module, title="Second")
    activity = Activity.objects.create(
        content_node=second,
        activity_type="bot_sim",
        title="Practice ticket",
        config={
            "persona": "random",
            "topics": [],
            "pass_threshold": 0.7,
            "max_exchanges": 6,
            # The older tests are about one ticket that must pass; the quota has its own tests.
            "required_tickets": 1,
            "require_average": True,
            **(config or {}),
        },
        max_attempts=max_attempts,
    )
    catalog.set_learning_order(version, order)
    if publish:
        version.publish(admin)
    return {
        "course": course,
        "version": version,
        "first": first,
        "second": second,
        "activity": activity,
        "author": author,
        "admin": admin,
    }


def post_json(client, url, data=None, **extra):
    return client.post(url, json.dumps(data or {}), content_type="application/json", **extra)


def u(name, *args):
    return reverse(f"sim_api:{name}", args=args)


def play(client, activity, replies, *, run_commits, finish=False):
    """Drive a whole ticket through the API as `client`'s user; returns the final payload."""
    import uuid

    with run_commits():
        payload = post_json(client, u("start", activity.pk)).json()
    sid = payload["id"]
    for text in replies:
        with run_commits():
            response = post_json(
                client, u("message", sid), {"text": text, "client_id": str(uuid.uuid4())}
            )
        assert response.status_code in (200, 202), response.content
        payload = client.get(u("session", sid)).json()
        if payload["state"] != "open":
            break
    if finish and payload["state"] == "open":
        with run_commits():
            payload = post_json(client, u("finish", sid)).json()
    with run_commits():
        pass
    return client.get(u("session", sid)).json()


def make_session(user, activity, scenario=None, *, turns=(), state="open"):
    """A session built directly, for tests that exercise one step."""
    from django.utils import timezone

    scenario = scenario or approved_scenarios(1)[0]
    now = timezone.now()
    session = services._create_session(user, activity, scenario, False, preview=False, now=now)
    for seq, (role, text) in enumerate(turns, start=2):
        SimTurn.objects.create(
            session=session, seq=seq, role=role, text=text, at=now, job_state="done"
        )
    if state != "open":
        SimSession.objects.filter(pk=session.pk).update(state=state)
        session.refresh_from_db()
    return session


def add_intern_turn(session, seq, text=GOOD, *, scores=None, tat=60, job_state="pending"):
    """An intern reply as the API would have stored it (not yet worked on by default)."""
    import uuid

    from django.utils import timezone

    now = timezone.now()
    return SimTurn.objects.create(
        session=session,
        seq=seq,
        role=SimTurn.Role.INTERN,
        text=text,
        at=now,
        client_id=uuid.uuid4(),
        tat_seconds=tat,
        scores=scores,
        job_state=job_state,
        job_enqueued_at=now,
    )


def turn_scores(c=4, e=4, a=4, k=4, tat=5, tat_seconds=60, docs=None, flags=()):
    from simbot_engine.evaluator import TurnScores

    return TurnScores(
        communication=c, empathy=e, accuracy=a, concreteness=k, tat=tat,
        tat_seconds=tat_seconds,
        notes={"communication": "ok", "empathy": "ok", "accuracy": "ok", "concreteness": "ok"},
        docs_relevance=docs, flags=list(flags),
    ).to_dict()  # fmt: skip


def scored_session(user, activity, rows, *, state="finishing", texts=None, scenario=None):
    """A conversation whose replies are already scored, ready to be finalised."""
    session = make_session(user, activity, scenario)
    seq = 2
    for i, row in enumerate(rows):
        text = (texts or {}).get(i, GOOD)
        add_intern_turn(session, seq, text, scores=row, job_state="done")
        SimTurn.objects.create(
            session=session,
            seq=seq + 1,
            role="customer",
            text="ok",
            at=session.started_at,
            job_state="done",
        )
        seq += 2
    SimSession.objects.filter(pk=session.pk).update(state=state)
    session.refresh_from_db()
    return session
