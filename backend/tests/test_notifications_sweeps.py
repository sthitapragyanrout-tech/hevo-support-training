"""The reminders: deadlines and overdue reviews, found by a periodic sweep. Every reminder is
raised once, re-running the sweep adds nothing, and a changed deadline is announced again. Time is
injected."""

from datetime import timedelta

import pytest

from apps.enrollment.models import Enrollment, ModuleExclusion
from apps.manual_sim import services as sims
from apps.notifications import events, services, sweeps, tasks
from apps.notifications.models import Notification
from apps.progress import services as progress
from tests.manual_sim_helpers import PASS, at, people, rated_course
from tests.written_quiz_helpers import ALL_RIGHT, cast, written_course

pytestmark = pytest.mark.django_db

ANSWER = "The pipeline stopped because the source password expired; rotate it and resume."


@pytest.fixture
def world(make_role_user):
    return {**rated_course(make_role_user), **people(make_role_user)}


def told(user, kind=None):
    rows = Notification.objects.filter(user=user)
    return list(rows.filter(kind=kind) if kind else rows)


def opened(world, user="learner"):
    """The learner has opened the simulation, so a deadline is running."""
    return sims.open_case(world[user], world["activity"].pk, now=at())


class TestLearnerDeadlines:
    def test_a_deadline_within_a_day_is_announced_once(self, world):
        case = opened(world)
        soon = case.due_at - timedelta(hours=5)
        first = sweeps.sweep(now=soon)
        (n,) = told(world["learner"], "due_soon")
        assert first["learner"] == 1
        assert "Customer reply" in n.title and "Hand it in by" in n.body
        assert n.link == f"/courses/{world['course'].pk}/lessons/{world['second'].pk}"
        assert sweeps.sweep(now=soon + timedelta(hours=1))["learner"] == 0  # not again
        assert len(told(world["learner"], "due_soon")) == 1

    def test_a_deadline_further_off_is_not_announced(self, world):
        case = opened(world)
        assert sweeps.sweep(now=case.due_at - timedelta(days=2))["learner"] == 0
        assert told(world["learner"]) == []

    def test_a_passed_deadline_is_announced_once_and_not_as_due_soon(self, world):
        case = opened(world)
        late = case.due_at + timedelta(hours=2)
        sweeps.sweep(now=late)
        sweeps.sweep(now=late + timedelta(hours=3))
        kinds = [n.kind for n in told(world["learner"])]
        assert kinds == ["overdue"]
        assert "past its deadline" in told(world["learner"])[0].title
        assert "Late work is accepted" in told(world["learner"])[0].body

    def test_an_ancient_deadline_is_not_news(self, world):
        case = opened(world)
        sweeps.sweep(now=case.due_at + timedelta(days=15))
        assert told(world["learner"]) == []

    def test_an_extension_is_a_new_deadline_and_is_announced_again(self, world):
        case = opened(world)
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        sims.extend(world["trainer"], case.pk, 3, "More time", now=case.due_at + timedelta(hours=2))
        case.refresh_from_db()
        sweeps.sweep(now=case.due_at - timedelta(hours=3))
        assert [n.kind for n in told(world["learner"])] == ["due_soon", "overdue"]

    def test_a_due_soon_reminder_comes_again_for_an_extended_deadline(self, world):
        case = opened(world)
        sweeps.sweep(now=case.due_at - timedelta(hours=5))
        sims.extend(world["trainer"], case.pk, 3, "More time", now=case.due_at - timedelta(hours=4))
        case.refresh_from_db()
        sweeps.sweep(now=case.due_at - timedelta(hours=5))
        assert [n.kind for n in told(world["learner"])] == ["due_soon", "due_soon"]
        assert len({n.dedupe_key for n in told(world["learner"])}) == 2

    def test_the_case_is_left_alone_once_handed_in(self, world):
        case = opened(world)
        sims.submit(world["learner"], world["activity"].pk, ANSWER, now=at())
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []

    def test_a_waived_or_closed_case_is_left_alone(self, world):
        case = opened(world)
        sims.waive(world["trainer"], case.pk, "Not needed")
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []

    def test_a_passed_activity_is_left_alone(self, world):
        case = opened(world)
        sub = sims.submit(world["learner"], world["activity"].pk, ANSWER, now=at())
        sims.rate(world["mentor"], sub.pk, PASS, {}, "Good.", now=at(hours=1))
        Notification.objects.all().delete()
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []

    def test_someone_no_longer_on_the_course_or_deactivated_is_left_alone(self, world):
        case = opened(world)
        Enrollment.objects.filter(user=world["learner"]).update(state=Enrollment.State.WITHDRAWN)
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []
        Enrollment.objects.filter(user=world["learner"]).update(state=Enrollment.State.ACTIVE)
        world["learner"].is_active = False
        world["learner"].save()
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []

    def test_a_module_switched_off_for_the_learner_is_left_alone(self, world):
        case = opened(world)
        row = Enrollment.objects.get(user=world["learner"])
        ModuleExclusion.objects.create(enrollment=row, node=world["second"].parent)
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["learner"]) == []

    def test_each_learner_is_told_about_their_own_deadline_only(self, world):
        case = opened(world)
        opened(world, "other")
        sweeps.sweep(now=case.due_at - timedelta(hours=2))
        assert len(told(world["learner"], "due_soon")) == 1
        assert len(told(world["other"], "due_soon")) == 1
        assert told(world["mentor"]) == [] and told(world["trainer"], "due_soon") == []


class TestOverdueReviews:
    def hand_in(self, world):
        return sims.submit(world["learner"], world["activity"].pk, ANSWER, now=at())

    def test_work_in_the_pool_that_is_overdue_tells_the_managers_not_every_mentor(self, world):
        sub = self.hand_in(world)
        sweeps.sweep(now=sub.review_due_at + timedelta(hours=1))
        for who in ("trainer", "root"):
            (n,) = told(world[who], "review_escalated")
            assert "in the pool is overdue" in n.title and n.link == f"/admin/ratings/{sub.pk}"
        assert told(world["mentor"], "review_escalated") == []
        assert told(world["mentor"], "review_overdue") == []

    def test_work_with_a_mentor_tells_that_mentor_when_overdue_and_managers_after_the_grace(
        self, world, settings
    ):
        from apps.manual_sim import assignments

        assignments.assign_mentor(world["learner"], world["course"], world["mentor"])
        sub = self.hand_in(world)
        due = sub.review_due_at
        out = sweeps.sweep(now=due + timedelta(hours=1))
        assert (out["mentors"], out["escalated"]) == (1, 0)
        assert len(told(world["mentor"], "review_overdue")) == 1
        assert told(world["trainer"], "review_escalated") == []
        grace = timedelta(hours=settings.MANUAL_SIM_ESCALATION_GRACE_HOURS)
        out = sweeps.sweep(now=due + grace + timedelta(hours=1))
        # every manager: the trainer and admin, and the course's own author and admin
        assert out["escalated"] == events.managers().count() == 4
        assert "open to anyone" in told(world["trainer"], "review_escalated")[0].title

    def test_running_it_again_raises_nothing_new(self, world):
        sub = self.hand_in(world)
        later = sub.review_due_at + timedelta(hours=1)
        sweeps.sweep(now=later)
        count = Notification.objects.count()
        assert sweeps.sweep(now=later + timedelta(hours=2)) == {
            "learner": 0,
            "mentors": 0,
            "escalated": 0,
            "digest": 0,
        }
        assert Notification.objects.count() == count

    def test_work_that_is_not_yet_overdue_or_is_done_raises_nothing(self, world):
        sub = self.hand_in(world)
        sweeps.sweep(now=sub.review_due_at - timedelta(hours=1))
        assert Notification.objects.filter(kind__startswith="review_").count() == 0
        sims.rate(world["mentor"], sub.pk, PASS, {}, "Good.", now=sub.review_due_at)
        sweeps.sweep(now=sub.review_due_at + timedelta(days=3))
        assert Notification.objects.filter(kind__startswith="review_").count() == 0

    def test_a_late_rating_clears_the_overdue_reminders(self, world):
        sub = self.hand_in(world)
        sweeps.sweep(now=sub.review_due_at + timedelta(hours=1))
        sims.rate(
            world["mentor"], sub.pk, PASS, {}, "Good.", now=sub.review_due_at + timedelta(hours=2)
        )
        reminders = Notification.objects.filter(kind="review_escalated")
        assert reminders.exists() and not reminders.filter(read_at__isnull=True).exists()

    def test_a_manager_is_not_reminded_about_their_own_work(self, world):
        sub = sims.submit(world["trainer"], world["activity"].pk, ANSWER, now=at())
        sweeps.sweep(now=sub.review_due_at + timedelta(hours=1))
        assert told(world["trainer"], "review_escalated") == []
        assert len(told(world["root"], "review_escalated")) == 1

    def test_overdue_marking_of_a_written_quiz_is_reminded_too(self, make_role_user):
        w = written_course(make_role_user, title="Q")
        w.update(cast(make_role_user))
        progress.submit_attempt(w["learner"], w["quiz"].pk, ALL_RIGHT)
        review = w["learner"].quiz_reviews.get()
        sweeps.sweep(now=review.review_due_at + timedelta(hours=1))
        (n,) = told(w["trainer"], "review_escalated")
        assert n.link == f"/admin/ratings/quiz/{review.pk}" and "Written" not in n.body


class TestTheDailyDigest:
    def overdue_two(self, world):
        a = opened(world)
        b = opened(world, "other")
        return max(a.due_at, b.due_at) + timedelta(hours=2)

    def test_managers_get_one_message_a_day_counting_learners_not_cases(self, world):
        late = self.overdue_two(world)
        out = sweeps.sweep(now=late)
        assert out["digest"] == events.managers().count() == 4  # each manager, once
        for who in ("trainer", "root"):
            (n,) = told(world[who], "overdue_digest")
            assert n.title == "2 learners are past a deadline" and n.link == "/admin/ratings"
        assert told(world["mentor"], "overdue_digest") == []
        assert sweeps.sweep(now=late + timedelta(hours=1))["digest"] == 0  # same day

    def test_the_next_day_it_comes_again_while_it_is_still_true(self, world):
        late = self.overdue_two(world)
        sweeps.sweep(now=late)
        sweeps.sweep(now=late + timedelta(days=1))
        assert len(told(world["trainer"], "overdue_digest")) == 2

    def test_nothing_overdue_means_no_digest(self, world):
        opened(world)
        assert sweeps.sweep(now=at())["digest"] == 0

    def test_one_overdue_learner_is_singular(self, world):
        case = opened(world)
        sweeps.sweep(now=case.due_at + timedelta(hours=1))
        assert told(world["trainer"], "overdue_digest")[0].title == "1 learner is past a deadline"


class TestTheTasks:
    def test_they_are_scheduled(self, settings):
        beat = {e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()}
        assert {"notifications.sweep", "notifications.prune"} <= beat

    def test_the_sweep_task_runs_and_is_safe_to_repeat(self, world):
        opened(world)
        assert set(tasks.sweep()) == {"learner", "mentors", "escalated", "digest"}
        assert set(tasks.sweep()) == {"learner", "mentors", "escalated", "digest"}

    def test_the_prune_task_deletes_old_read_notices(self, world):
        from django.utils import timezone

        made = services.notify(world["learner"], "k", "old")
        Notification.objects.filter(pk=made.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )
        assert tasks.prune() == 1

    def test_the_task_names_are_the_ones_the_scheduler_uses(self):
        assert tasks.sweep.name == "notifications.sweep"
        assert tasks.prune.name == "notifications.prune"
