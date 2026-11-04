"""Races: two requests at once must never make two submissions, two ratings, two holders of one
claim, or a closed case with work still waiting. These need real row locks, so they run on
Postgres only (as the quiz and practice-ticket race tests do)."""

import threading

import pytest
from django.db import IntegrityError, connection

from apps.manual_sim import services
from apps.manual_sim.errors import Conflict, SimError
from apps.manual_sim.models import RubricScore, SimCase, SimSubmission
from apps.progress.models import ActivityAttempt
from tests.manual_sim_helpers import PASS, at, people, rated_course

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor == "sqlite", reason="needs row locks"),
]


@pytest.fixture
def world(make_role_user, media_dirs):
    return {**rated_course(make_role_user), **people(make_role_user)}


def run_together(jobs):
    """Run each job in its own thread and database connection, starting together."""
    results: list = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def worker(i, job):
        try:
            barrier.wait()
            results[i] = ("ok", job())
        except (SimError, IntegrityError) as exc:
            results[i] = ("refused", exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def outcomes(results):
    return sorted(kind for kind, _ in results)


def test_a_double_click_makes_one_submission(world):
    def go():
        return services.submit(world["learner"], world["activity"].pk, "My reply.", now=at())

    results = run_together([go] * 5)
    assert outcomes(results).count("ok") == 1
    assert all(isinstance(r, Conflict) for kind, r in results if kind == "refused")
    assert SimSubmission.objects.count() == 1 and SimCase.objects.count() == 1


def test_two_raters_cannot_both_rate_the_same_work(world):
    sub = services.submit(world["learner"], world["activity"].pk, "My reply.", now=at())

    def rate_as(who):
        return lambda: services.rate(world[who], sub.pk, PASS, {}, "Done.", now=at(hours=1))

    results = run_together([rate_as("mentor"), rate_as("mentor2"), rate_as("trainer")])
    assert outcomes(results).count("ok") == 1
    assert RubricScore.objects.filter(submission=sub).count() == 2
    assert ActivityAttempt.objects.count() == 1
    sub.refresh_from_db()
    assert sub.state == "rated" and sub.rated_by is not None


def test_only_one_rater_can_hold_a_pool_item(world):
    sub = services.submit(world["learner"], world["activity"].pk, "My reply.", now=at())
    results = run_together(
        [
            lambda: services.claim(world["mentor"], sub.pk, now=at(hours=1)),
            lambda: services.claim(world["mentor2"], sub.pk, now=at(hours=1)),
        ]
    )
    # Both may succeed in turn only if the second saw the first's claim and was allowed — it
    # is not, so exactly one holds it.
    assert outcomes(results).count("ok") == 1
    held = SimSubmission.objects.get().claimed_by
    assert held in (world["mentor"], world["mentor2"])


def test_closing_while_work_is_being_handed_in_never_leaves_a_closed_case_with_work_waiting(world):
    case = services.open_case(world["learner"], world["activity"].pk, now=at())
    results = run_together(
        [
            lambda: services.submit(
                world["learner"], world["activity"].pk, "My reply.", now=at(hours=1)
            ),
            lambda: services.close(world["trainer"], case.pk, "Left.", now=at(hours=1)),
        ]
    )
    case.refresh_from_db()
    assert case.closed_at is not None or outcomes(results).count("ok") >= 1
    if case.closed_at is not None:
        assert not SimSubmission.objects.filter(case=case, state="submitted").exists()


def test_rating_while_the_case_is_being_closed_ends_one_way_or_the_other(world):
    sub = services.submit(world["learner"], world["activity"].pk, "My reply.", now=at())
    case = SimCase.objects.get()
    run_together(
        [
            lambda: services.rate(world["mentor"], sub.pk, PASS, {}, "Done.", now=at(hours=1)),
            lambda: services.close(world["trainer"], case.pk, "Left.", now=at(hours=1)),
        ]
    )
    sub.refresh_from_db()
    case.refresh_from_db()
    # Either it was rated first (then it was a pass, so closing was refused) or it was closed
    # first (then the work was withdrawn and the rating refused). Never both.
    assert (sub.state == "rated") != (case.closed_at is not None)
    assert not (case.closed_at is not None and sub.state == "rated")
