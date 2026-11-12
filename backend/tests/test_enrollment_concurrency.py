"""Races around enrollment: a double click, two moves at once, a rating arriving while the
learner is being moved. They need real row locks, so they run on Postgres only."""

import threading

import pytest
from django.db import IntegrityError, connection

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity, ContentNode
from apps.enrollment import migration, modules, services
from apps.enrollment.errors import EnrollmentError
from apps.enrollment.models import Enrollment, VersionMove
from apps.manual_sim import services as rated
from apps.manual_sim.errors import SimError
from apps.manual_sim.models import SimCase
from apps.progress import services as progress
from apps.progress.models import ActivityAttempt, ActivityProgress, LessonCompletion
from tests.enrollment_helpers import course_with
from tests.manual_sim_helpers import PASS, at, people, rated_course

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.real_enrollment,
    pytest.mark.skipif(connection.vendor == "sqlite", reason="needs row locks"),
]


def run_together(jobs):
    results: list = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def worker(i, job):
        try:
            barrier.wait()
            results[i] = ("ok", job())
        except (EnrollmentError, SimError, IntegrityError) as exc:
            results[i] = ("refused", exc)
        except Exception as exc:  # a crash is a failure, and says what it was
            results[i] = ("crashed", exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_a_double_click_enrolls_once(make_role_user):
    w = course_with(make_role_user)
    learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")

    results = run_together([lambda: services.enroll(learner, w["course"])] * 5)
    assert [kind for kind, _ in results] == ["ok"] * 5  # every click is a success
    assert Enrollment.objects.filter(user=learner, course=w["course"]).count() == 1


def test_two_moves_at_once_make_one_move(make_role_user):
    w = course_with(make_role_user)
    learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    row, _ = services.enroll(learner, w["course"])
    progress.complete_activity(learner, w["reading"].pk)
    draft = catalog.get_or_create_draft(w["course"])
    draft.publish(w["admin"])

    results = run_together([lambda: migration.apply(row, to_version_id=draft.pk)] * 4)
    assert [kind for kind, _ in results].count("ok") == 1
    assert VersionMove.objects.count() == 1
    assert ActivityProgress.objects.filter(user=learner).count() == 1
    assert ActivityProgress.objects.get(user=learner).activity.content_node.course_version == draft


@pytest.mark.parametrize("round_", range(3))
def test_a_rating_arriving_during_the_move_leaves_the_new_lesson_settled(
    make_role_user, media_dirs, round_
):
    w = {
        **rated_course(make_role_user, order="sequential", title=f"Race {round_}"),
        **people(make_role_user),
    }
    row, _ = services.enroll(w["learner"], w["course"], mentor=w["mentor"])
    progress.complete_activity(w["learner"], w["first"].activities.get().pk)
    progress.complete_lesson(w["learner"], w["first"].pk)
    sub = rated.submit(w["learner"], w["activity"].pk, "My reply.", now=at())
    progress.complete_lesson(w["learner"], w["second"].pk)
    draft = catalog.get_or_create_draft(w["course"])
    draft.publish(w["admin"])

    results = run_together(
        [
            lambda: rated.rate(w["mentor"], sub.pk, PASS, {}, "Good.", now=at(hours=1)),
            lambda: migration.apply(row, to_version_id=draft.pk),
        ]
    )
    assert [kind for kind, _ in results] == ["ok", "ok"], results

    new_activity = Activity.objects.get(
        content_node__course_version=draft, activity_type="manual_sim"
    )
    assert SimCase.objects.get(user=w["learner"]).activity == new_activity
    assert ActivityAttempt.objects.filter(user=w["learner"]).count() == 1
    assert (
        ActivityProgress.objects.get(user=w["learner"], activity=new_activity).state == "completed"
    )
    lesson = LessonCompletion.objects.get(user=w["learner"], node=new_activity.content_node)
    assert lesson.provisional is False


def test_two_module_changes_at_once_end_in_one_of_them_with_no_duplicates(make_role_user):
    w = course_with(make_role_user)
    version = w["version"]
    extra = [
        ContentNode.objects.create(
            course_version=version,
            parent=version.root_node,
            kind=ContentNode.Kind.SEGMENT,
            title=f"M{i}",
            slug=f"m{i}",
            order=10 + i,
        )
        for i in range(3)
    ]
    learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    row, _ = services.enroll(learner, w["course"])
    first, a, b, c = w["module"], *extra
    choices = [[first.pk], [first.pk, a.pk], [b.pk, c.pk], [first.pk, c.pk]]

    results = run_together([lambda ids=ids: modules.set_modules(row, ids) for ids in choices])
    assert [kind for kind, _ in results] == ["ok"] * 4  # nobody hits the unique constraint
    off = modules.excluded_of(row)
    everything = {first.pk, a.pk, b.pk, c.pk}
    assert off in [everything - set(ids) for ids in choices]  # exactly one request's result


def test_two_quick_submits_of_a_written_quiz_park_one_attempt(make_role_user):
    from apps.manual_sim.models import QuizReview
    from tests.written_quiz_helpers import ALL_RIGHT, written_course

    w = written_course(make_role_user, title="Race")
    learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    services.enroll(learner, w["course"])

    results = run_together([lambda: progress.submit_attempt(learner, w["quiz"].pk, ALL_RIGHT)] * 4)
    kinds = [kind for kind, _ in results]
    assert kinds.count("ok") == 1, results
    # The rest were refused for the right reason (a try is already waiting), not crashed.
    others = [value for kind, value in results if kind != "ok"]
    assert all(isinstance(v, progress.AttemptNotAllowed) for v in others), others
    assert QuizReview.objects.filter(user=learner).count() == 1


def test_sweeps_running_at_once_raise_each_reminder_exactly_once(make_role_user):
    from datetime import timedelta

    from apps.manual_sim import services as sims
    from apps.notifications import sweeps
    from apps.notifications.models import Notification
    from tests.manual_sim_helpers import at, people, rated_course

    w = {**rated_course(make_role_user), **people(make_role_user)}
    services.enroll(w["learner"], w["course"])
    case = sims.open_case(w["learner"], w["activity"].pk, now=at())
    late = case.due_at + timedelta(hours=1)

    results = run_together([lambda: sweeps.sweep(now=late)] * 5)
    assert [kind for kind, _ in results] == ["ok"] * 5, results
    assert Notification.objects.filter(user=w["learner"], kind="overdue").count() == 1
    # And one digest per manager, however many sweeps ran together.
    managers = Notification.objects.filter(kind="overdue_digest")
    assert managers.count() == managers.values("user").distinct().count() > 0
