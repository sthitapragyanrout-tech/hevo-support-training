"""Certificates: the interim course score, when one is issued, that it is never taken back by
itself, who may see one, and the course setting that switches it on."""

import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.catalog import services as catalog
from apps.catalog.models import Activity
from apps.certification import scoring
from apps.certification import services as certs
from apps.certification.models import Certificate, CertificatePolicy
from apps.enrollment import services as enrollment
from apps.notifications.models import Notification
from apps.progress import services as progress
from apps.progress import summary

pytestmark = [pytest.mark.django_db, pytest.mark.real_enrollment]


def quiz_config(n: int, pass_threshold: float = 0.2):
    return {
        "questions": [{"text": f"Q{i}", "choices": ["A", "B"], "answer": 0} for i in range(n)],
        "pass_threshold": pass_threshold,
    }


def answers(n: int, right: int):
    return [[0] if i < right else [1] for i in range(n)]


@pytest.fixture
def world(make_role_user):
    """A course with one module: lesson One (a 5-question quiz), lesson Two (a 5-question quiz)
    and an optional lesson Extra (a reading)."""
    author = make_role_user(Role.Name.TRAINER, username="tom", email="tom@e.com")
    admin = make_role_user(Role.Name.ADMIN, username="ada", email="ada@e.com")
    learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    other = make_role_user(Role.Name.LEARNER, username="oth", email="oth@e.com")
    course = catalog.create_course(title="Support basics", user=author)
    v = catalog.open_version(course)
    module = catalog.add_node(v.root_node, title="Module")
    one = catalog.add_node(module, title="One")
    two = catalog.add_node(module, title="Two")
    extra = catalog.add_node(module, title="Extra")
    extra.is_required = False
    extra.save()
    q1 = Activity.objects.create(
        content_node=one, activity_type="mcq", title="Quiz one", config=quiz_config(5)
    )
    q2 = Activity.objects.create(
        content_node=two, activity_type="mcq", title="Quiz two", config=quiz_config(5)
    )
    Activity.objects.create(
        content_node=extra,
        activity_type="reading",
        title="Read",
        config={"source_url": "https://x.io"},
    )
    v.publish(admin)
    enrollment.enroll(learner, course)
    return {
        "author": author,
        "admin": admin,
        "learner": learner,
        "other": other,
        "course": course,
        "version": v,
        "one": one,
        "two": two,
        "q1": q1,
        "q2": q2,
    }


def switch_on(world, threshold=70, **weights):
    CertificatePolicy.objects.update_or_create(
        course=world["course"],
        defaults={"enabled": True, "threshold": threshold, **weights},
    )


def finish(world, right1: int, right2: int, capture):
    user = world["learner"]
    with capture(execute=True):
        progress.submit_attempt(user, world["q1"].pk, answers(5, right1))
        progress.complete_lesson(user, world["one"].pk)
        progress.submit_attempt(user, world["q2"].pk, answers(5, right2))
        progress.complete_lesson(user, world["two"].pk)


def mine(world):
    return Certificate.objects.filter(user=world["learner"], course=world["course"])


class TestScoring:
    def course(self, quizzes=(), practice=(), rated=()):
        return {
            "quizzes": [{"best": b} for b in quizzes],
            "practice": [{"average": a} for a in practice],
            "rated": [
                {"last_score": s, "status": "waived" if s == "waived" else "passed"}
                if s != "waived"
                else {"last_score": None, "status": "waived"}
                for s in rated
            ],
        }

    def test_each_kind_is_averaged_then_weighted(self):
        c = self.course(quizzes=[1.0, 0.5], practice=[4.0], rated=[3.0])
        result = scoring.course_score(c, {"quiz": 2, "practice": 1, "rated": 1})
        # quiz 0.75 (x2), practice 0.8, rated 0.6 -> (1.5 + 0.8 + 0.6) / 4
        assert result["score"] == pytest.approx(0.725)
        assert result["missing"] == []
        assert result["parts"]["quiz"] == {"average": 0.75, "scored": 2, "items": 2, "weight": 2}

    def test_a_kind_the_course_lacks_drops_out_and_the_others_share_its_weight(self):
        c = self.course(quizzes=[0.8])
        assert scoring.course_score(c, {"quiz": 1, "practice": 5, "rated": 5})["score"] == 0.8

    def test_a_kind_with_items_but_no_result_yet_is_missing(self):
        c = self.course(quizzes=[0.9], practice=[None])
        result = scoring.course_score(c, {"quiz": 1, "practice": 1, "rated": 1})
        assert result["missing"] == ["practice"] and result["score"] == 0.9

    def test_weight_zero_leaves_a_kind_out_entirely(self):
        c = self.course(quizzes=[1.0], rated=[1.0])
        result = scoring.course_score(c, {"quiz": 1, "practice": 1, "rated": 0})
        assert result["score"] == 1.0 and result["missing"] == []

    def test_waived_work_is_not_counted(self):
        c = self.course(quizzes=[0.5], rated=["waived"])
        result = scoring.course_score(c, {"quiz": 1, "practice": 1, "rated": 1})
        assert result["score"] == 0.5 and result["parts"]["rated"]["items"] == 0

    def test_untaken_quizzes_are_not_averaged_in(self):
        c = self.course(quizzes=[1.0, None])
        assert scoring.course_score(c, {"quiz": 1})["score"] == 1.0


class TestIssuing:
    def test_nothing_without_a_policy_switched_on(self, world, django_capture_on_commit_callbacks):
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        assert not mine(world).exists()

    def test_issued_on_finishing_above_the_threshold_with_a_snapshot_and_a_notification(
        self, world, django_capture_on_commit_callbacks
    ):
        switch_on(world)
        finish(world, 5, 4, django_capture_on_commit_callbacks)
        (cert,) = mine(world)
        assert cert.score == pytest.approx(0.9) and cert.threshold == 70
        assert cert.weights == {"quiz": 1, "practice": 1, "rated": 1}
        assert cert.breakdown["quiz"]["average"] == pytest.approx(0.9)
        assert cert.course_title == "Support basics" and cert.version == world["version"]
        note = Notification.objects.get(user=world["learner"], kind=certs.CERTIFICATE_EARNED)
        assert note.link == f"/certificates/{cert.code}"

    def test_exactly_at_the_threshold_counts(self, world, django_capture_on_commit_callbacks):
        switch_on(world, threshold=70)
        finish(world, 5, 2, django_capture_on_commit_callbacks)  # (1.0 + 0.4) / 2 = 0.7
        assert mine(world).count() == 1

    def test_below_the_threshold_nothing(self, world, django_capture_on_commit_callbacks):
        switch_on(world, threshold=71)
        finish(world, 5, 2, django_capture_on_commit_callbacks)
        assert not mine(world).exists()
        st = summary.course_summary(world["learner"], world["learner"].enrollments.get())
        assert st["certification"]["score"] == pytest.approx(0.7)
        assert st["certification"]["eligible"] is False

    def test_not_before_every_required_lesson_is_done(
        self, world, django_capture_on_commit_callbacks
    ):
        switch_on(world)
        with django_capture_on_commit_callbacks(execute=True):
            progress.submit_attempt(world["learner"], world["q1"].pk, answers(5, 5))
            progress.complete_lesson(world["learner"], world["one"].pk)
        assert not mine(world).exists()

    def test_the_optional_lesson_is_not_needed(self, world, django_capture_on_commit_callbacks):
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        assert mine(world).count() == 1

    def test_raising_the_bar_later_never_takes_it_back(
        self, world, django_capture_on_commit_callbacks
    ):
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        with django_capture_on_commit_callbacks(execute=True):
            certs.set_policy(world["course"], {"threshold": 100, "enabled": False})
        assert mine(world).get().revoked_at is None

    def test_switching_it_on_issues_to_people_who_already_qualify(
        self, world, django_capture_on_commit_callbacks
    ):
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        assert not mine(world).exists()
        with django_capture_on_commit_callbacks(execute=True):
            certs.set_policy(world["course"], {"enabled": True, "threshold": 80})
        assert mine(world).count() == 1

    def test_a_withdrawn_learner_gets_nothing(self, world, django_capture_on_commit_callbacks):
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        enrollment.withdraw(world["learner"].enrollments.get(), "left")
        with django_capture_on_commit_callbacks(execute=True):
            certs.set_policy(world["course"], {"enabled": True})
        assert not mine(world).exists()

    def test_a_course_with_no_scored_work_is_earned_by_finishing_it(
        self, make_role_user, django_capture_on_commit_callbacks
    ):
        author = make_role_user(Role.Name.TRAINER, username="t2", email="t2@e.com")
        admin = make_role_user(Role.Name.ADMIN, username="a2", email="a2@e.com")
        learner = make_role_user(Role.Name.LEARNER, username="l2", email="l2@e.com")
        course = catalog.create_course(title="Readings", user=author)
        v = catalog.open_version(course)
        lesson = catalog.add_node(catalog.add_node(v.root_node, title="M"), title="L")
        reading = Activity.objects.create(
            content_node=lesson,
            activity_type="reading",
            title="R",
            config={"source_url": "https://x.io"},
        )
        v.publish(admin)
        enrollment.enroll(learner, course)
        CertificatePolicy.objects.create(course=course, enabled=True)
        with django_capture_on_commit_callbacks(execute=True):
            progress.complete_activity(learner, reading.pk)
            progress.complete_lesson(learner, lesson.pk)
        cert = Certificate.objects.get(user=learner)
        assert cert.score is None

    def test_evaluating_twice_issues_once(self, world, django_capture_on_commit_callbacks):
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        row = world["learner"].enrollments.get()
        assert certs.evaluate(row) is None
        assert mine(world).count() == 1


class TestRevoking:
    @pytest.fixture
    def cert(self, world, django_capture_on_commit_callbacks):
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        return mine(world).get()

    def call(self, client, user, name, pk, data=None):
        client.force_login(user)
        return client.post(
            reverse(f"console_api:{name}", args=(pk,)),
            json.dumps(data or {}),
            content_type="application/json",
        )

    def test_revoke_needs_a_reason_and_is_audited(self, client, world, cert):
        assert self.call(client, world["admin"], "certificate-revoke", cert.pk).status_code == 400
        done = self.call(
            client, world["admin"], "certificate-revoke", cert.pk, {"reason": "Copied answers"}
        )
        assert done.status_code == 200 and done.json()["revoked"] is True
        again = self.call(client, world["admin"], "certificate-revoke", cert.pk, {"reason": "x"})
        assert again.status_code == 409
        entry = AuditLog.objects.get(action="certificates.revoke")
        assert entry.changes == {"reason": "Copied answers"}

    def test_a_revoked_certificate_is_not_issued_again_by_itself_but_can_be_restored(
        self, client, world, cert, django_capture_on_commit_callbacks
    ):
        certs.revoke(cert, "Mistake", by=world["admin"])
        assert certs.evaluate(world["learner"].enrollments.get()) is None
        certs.evaluate_for(world["learner"].pk, world["course"].pk)
        assert mine(world).count() == 1 and mine(world).get().revoked_at is not None
        done = self.call(client, world["admin"], "certificate-restore", cert.pk)
        assert done.status_code == 200 and done.json()["revoked"] is False
        assert AuditLog.objects.filter(action="certificates.restore").count() == 1

    def test_learners_and_mentors_cannot_revoke(self, client, make_role_user, world, cert):
        mentor = make_role_user(Role.Name.MENTOR, username="mia", email="mia@e.com")
        for who in (world["learner"], mentor):
            response = self.call(client, who, "certificate-revoke", cert.pk, {"reason": "x"})
            assert response.status_code == 403
        assert mine(world).get().revoked_at is None


class TestThePage:
    @pytest.fixture
    def cert(self, world, django_capture_on_commit_callbacks):
        world["learner"].first_name, world["learner"].last_name = "Lea", "Learner"
        world["learner"].employee_id = "E123"
        world["learner"].save()
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        return mine(world).get()

    def get(self, client, user, code):
        client.force_login(user)
        return client.get(reverse("certificates_api:certificate", args=(code,)))

    def test_the_owner_sees_their_certificate_without_staff_details(self, client, world, cert):
        body = self.get(client, world["learner"], cert.code).json()
        assert body["name"] == "Lea Learner" and body["employee_id"] == "E123"
        assert body["course_title"] == "Support basics" and body["score"] == 1.0
        assert "breakdown" not in body and "revoked_reason" not in body

    def test_another_learner_gets_not_found(self, client, world, cert):
        assert self.get(client, world["other"], cert.code).status_code == 404
        assert self.get(client, world["other"], "NOSUCHCODE").status_code == 404

    def test_staff_see_it_with_the_breakdown(self, client, world, cert):
        body = self.get(client, world["admin"], cert.code).json()
        assert body["breakdown"]["quiz"]["average"] == 1.0 and body["id"] == cert.pk

    def test_a_revoked_one_is_gone_for_the_owner_but_staff_still_see_it(self, client, world, cert):
        certs.revoke(cert, "Mistake", by=world["admin"])
        assert self.get(client, world["learner"], cert.code).status_code == 404
        assert self.get(client, world["admin"], cert.code).json()["revoked"] is True

    def test_signed_out_people_get_nothing(self, client, cert):
        response = client.get(reverse("certificates_api:certificate", args=(cert.code,)))
        assert response.status_code in (401, 403)


class TestMyProgress:
    def test_the_learner_sees_score_threshold_and_certificate_but_no_breakdown(
        self, world, django_capture_on_commit_callbacks
    ):
        switch_on(world)
        finish(world, 5, 5, django_capture_on_commit_callbacks)
        (course,) = summary.learner_summary(world["learner"])["courses"]
        st = course["certification"]
        assert st["enabled"] and st["threshold"] == 70 and st["score"] == 1.0
        assert st["certificate"]["code"] == mine(world).get().code
        assert "parts" not in st

    def test_switched_off_says_so(self, world):
        (course,) = summary.learner_summary(world["learner"])["courses"]
        assert course["certification"] == {"enabled": False, "certificate": None}


class TestThePolicyEndpoint:
    def url(self, world):
        return reverse("authoring_api:certificate-policy", args=(world["course"].pk,))

    def put(self, client, user, world, data):
        client.force_login(user)
        return client.put(self.url(world), json.dumps(data), content_type="application/json")

    def test_defaults_then_change_and_audit(self, client, world):
        client.force_login(world["author"])
        body = client.get(self.url(world)).json()
        assert body["enabled"] is False and body["threshold"] == 70
        assert body["weights"] == {"quiz": 1, "practice": 1, "rated": 1}
        done = self.put(
            client,
            world["author"],
            world,
            {"enabled": True, "threshold": 80, "weights": {"quiz": 2, "rated": 0}},
        )
        assert done.status_code == 200
        assert done.json()["weights"] == {"quiz": 2, "practice": 1, "rated": 0}
        entry = AuditLog.objects.get(action="certificates.policy")
        assert entry.changes == {
            "enabled": [False, True],
            "threshold": [70, 80],
            "quiz": [1, 2],
            "rated": [1, 0],
        }

    @pytest.mark.parametrize(
        "data",
        [
            {"threshold": 0},
            {"threshold": 101},
            {"threshold": "70"},
            {"enabled": "yes"},
            {"weights": {"quiz": -1}},
            {"weights": {"reading": 1}},
            {"weights": {"quiz": 0, "practice": 0, "rated": 0}},
        ],
    )
    def test_bad_values_are_refused(self, client, world, data):
        assert self.put(client, world["author"], world, data).status_code == 400
        assert not CertificatePolicy.objects.exists()

    def test_learners_cannot_read_or_change_it(self, client, world):
        client.force_login(world["learner"])
        assert client.get(self.url(world)).status_code == 403
        assert self.put(client, world["learner"], world, {"enabled": True}).status_code == 403


def test_issued_at_is_recent(world, django_capture_on_commit_callbacks):
    switch_on(world)
    finish(world, 5, 5, django_capture_on_commit_callbacks)
    assert (timezone.now() - mine(world).get().issued_at).total_seconds() < 60


def test_the_back_fill_command_issues_what_is_earned(world, django_capture_on_commit_callbacks):
    from io import StringIO

    from django.core.management import call_command

    finish(world, 5, 5, django_capture_on_commit_callbacks)
    CertificatePolicy.objects.create(course=world["course"], enabled=True)
    out = StringIO()
    call_command("evaluate_certificates", stdout=out)
    assert mine(world).count() == 1 and "1 certificate(s) issued" in out.getvalue()
    call_command("evaluate_certificates", "--course", world["course"].slug, stdout=out)
    assert mine(world).count() == 1
