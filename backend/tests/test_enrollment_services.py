"""Enrolling, withdrawing, mentors, programs and bulk lists (the rules, not the HTTP)."""

import pytest

from apps.accounts.models import Role, User
from apps.bot_sim import services as sim
from apps.bot_sim.models import SimSession
from apps.catalog import services as catalog
from apps.enrollment import access, services
from apps.enrollment.errors import Conflict, EnrollmentError
from apps.enrollment.models import Enrollment, Program
from apps.manual_sim import assignments
from apps.manual_sim.models import MentorAssignment
from apps.progress.models import ActivityProgress
from tests.enrollment_helpers import course_with, publish_next
from tests.sim_helpers import approved_scenarios, sim_course

pytestmark = [pytest.mark.django_db, pytest.mark.real_enrollment]


@pytest.fixture
def world(make_role_user):
    w = course_with(make_role_user)
    w["lea"] = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    w["oth"] = make_role_user(Role.Name.LEARNER, username="oth", email="oth@e.com")
    w["mentor"] = make_role_user(Role.Name.MENTOR, username="mia", email="mia@e.com")
    w["trainer"] = make_role_user(Role.Name.TRAINER, username="tom", email="tom@e.com")
    return w


def second_course(make_role_user, title="Second course"):
    other = course_with(make_role_user, title=title)
    return other


class TestEnroll:
    def test_pins_the_latest_published_version(self, world):
        row, outcome = services.enroll(world["lea"], world["course"], by=world["trainer"])
        assert outcome == services.ENROLLED
        assert row.version == world["version"] and row.state == Enrollment.State.ACTIVE
        assert row.enrolled_by == world["trainer"] and row.source == Enrollment.Source.MANUAL
        assert access.can_use(world["lea"], world["version"])

    def test_it_pins_the_version_current_at_that_moment(self, world):
        first, _ = services.enroll(world["lea"], world["course"])
        newer = publish_next(world)
        second, _ = services.enroll(world["oth"], world["course"])
        first.refresh_from_db()
        assert first.version == world["version"] and second.version == newer

    def test_enrolling_twice_is_harmless(self, world):
        a, first = services.enroll(world["lea"], world["course"])
        b, second = services.enroll(world["lea"], world["course"])
        assert (first, second) == (services.ENROLLED, services.ALREADY) and a.pk == b.pk
        assert Enrollment.objects.count() == 1

    def test_a_course_with_nothing_published_cannot_be_enrolled_on(self, make_role_user, world):
        draft_only = course_with(make_role_user, title="Draft", publish=False)
        with pytest.raises(Conflict, match="no published version"):
            services.enroll(world["lea"], draft_only["course"])
        assert not Enrollment.objects.exists()

    def test_an_archived_course_cannot_be_enrolled_on(self, world):
        catalog.archive_course(world["course"])
        with pytest.raises(Conflict, match="archived"):
            services.enroll(world["lea"], world["course"])

    def test_a_deactivated_account_cannot_be_enrolled(self, world):
        User.objects.filter(pk=world["lea"].pk).update(is_active=False)
        world["lea"].refresh_from_db()
        with pytest.raises(EnrollmentError, match="deactivated"):
            services.enroll(world["lea"], world["course"])

    def test_a_mentor_comes_with_the_enrollment(self, world):
        services.enroll(world["lea"], world["course"], mentor=world["mentor"], by=world["trainer"])
        assert assignments.mentor_for(world["lea"], world["course"]) == world["mentor"]

    def test_a_mentor_who_cannot_be_used_stops_the_enrollment_altogether(self, world):
        with pytest.raises(EnrollmentError, match="can’t be this learner’s mentor"):
            services.enroll(world["lea"], world["course"], mentor=world["oth"])
        assert not Enrollment.objects.exists() and not MentorAssignment.objects.exists()
        with pytest.raises(EnrollmentError):
            services.enroll(world["mentor"], world["course"], mentor=world["mentor"])

    def test_the_mentor_is_per_course(self, make_role_user, world):
        other = course_with(make_role_user, title="Other")
        services.enroll(world["lea"], world["course"], mentor=world["mentor"])
        services.enroll(world["lea"], other["course"])
        assert assignments.mentor_for(world["lea"], other["course"]) is None


class TestWithdraw:
    def test_hides_the_course_and_keeps_everything_they_did(self, world):
        row, _ = services.enroll(world["lea"], world["course"])
        ActivityProgress.objects.create(
            user=world["lea"], activity=world["reading"], started_at=row.enrolled_at
        )
        gone = services.withdraw(row, " Left the team ", by=world["trainer"])
        assert gone.state == Enrollment.State.WITHDRAWN and gone.withdrawn_reason == "Left the team"
        assert gone.withdrawn_by == world["trainer"] and gone.withdrawn_at is not None
        assert not access.can_use(world["lea"], world["version"])
        assert ActivityProgress.objects.filter(user=world["lea"]).count() == 1

    def test_withdrawing_twice_is_refused(self, world):
        row, _ = services.enroll(world["lea"], world["course"])
        services.withdraw(row, "", by=None)
        with pytest.raises(Conflict, match="already withdrawn"):
            services.withdraw(row, "", by=None)

    def test_a_long_reason_is_refused(self, world):
        row, _ = services.enroll(world["lea"], world["course"])
        with pytest.raises(EnrollmentError, match="300"):
            services.withdraw(row, "x" * 301)

    def test_the_mentor_is_released(self, world):
        row, _ = services.enroll(world["lea"], world["course"], mentor=world["mentor"])
        services.withdraw(row, "")
        assert not MentorAssignment.objects.exists()

    def test_an_open_practice_ticket_is_closed_uncounted(self, make_role_user):
        w = sim_course(make_role_user)
        approved_scenarios(3)
        learner = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
        row, _ = services.enroll(learner, w["course"])
        session = sim.start(learner, w["activity"].pk)
        assert session.state == SimSession.State.OPEN
        services.withdraw(row, "")
        session.refresh_from_db()
        assert session.state == SimSession.State.ABANDONED
        assert session.abandon_reason == "withdrawn"

    def test_re_enrolling_brings_the_same_row_back_on_the_latest_version(self, world):
        row, _ = services.enroll(world["lea"], world["course"])
        services.withdraw(row, "Left")
        newer = publish_next(world)
        back, outcome = services.enroll(world["lea"], world["course"], by=world["trainer"])
        assert outcome == services.REACTIVATED and back.pk == row.pk
        assert back.version == newer and back.state == Enrollment.State.ACTIVE
        assert back.withdrawn_at is None and back.withdrawn_reason == ""
        assert Enrollment.objects.count() == 1


class TestChangeMentor:
    def test_set_change_and_clear(self, make_role_user, world):
        second = make_role_user(Role.Name.MENTOR, username="max", email="max@e.com")
        row, _ = services.enroll(world["lea"], world["course"])
        services.change_mentor(row, world["mentor"])
        assert assignments.mentor_for(world["lea"], world["course"]) == world["mentor"]
        services.change_mentor(row, second)
        assert assignments.mentor_for(world["lea"], world["course"]) == second
        services.change_mentor(row, None)
        assert assignments.mentor_for(world["lea"], world["course"]) is None

    def test_a_bad_mentor_changes_nothing(self, world):
        row, _ = services.enroll(world["lea"], world["course"], mentor=world["mentor"])
        with pytest.raises(EnrollmentError):
            services.change_mentor(row, world["oth"])
        assert assignments.mentor_for(world["lea"], world["course"]) == world["mentor"]

    def test_a_withdrawn_learner_has_no_mentor_to_change(self, world):
        row, _ = services.enroll(world["lea"], world["course"])
        services.withdraw(row, "")
        with pytest.raises(Conflict):
            services.change_mentor(row, world["mentor"])


class TestPrograms:
    @pytest.fixture
    def program(self, make_role_user, world):
        other = course_with(make_role_user, title="Second")
        no_release = course_with(make_role_user, title="Unreleased", publish=False)
        program = services.save_program(
            None,
            name="Cohort A",
            courses=[
                (world["course"].pk, True),
                (other["course"].pk, True),
                (no_release["course"].pk, False),
            ],
            by=world["trainer"],
        )
        return {"program": program, "other": other, "no_release": no_release}

    def test_it_keeps_its_courses_in_order(self, world, program):
        titles = [c.pk for c in services.program_courses(program["program"])]
        assert titles == [
            world["course"].pk,
            program["other"]["course"].pk,
            program["no_release"]["course"].pk,
        ]

    def test_enrolling_in_it_enrolls_on_each_course_and_reports_the_one_it_cannot(
        self, world, program
    ):
        steps = services.enroll_program(
            world["lea"], program["program"], mentor=world["mentor"], by=world["trainer"]
        )
        assert [s.outcome for s in steps] == [services.ENROLLED, services.ENROLLED, "skipped"]
        assert "no published version" in steps[2].detail
        rows = Enrollment.objects.filter(user=world["lea"])
        assert rows.count() == 2
        assert {r.program_id for r in rows} == {program["program"].pk}
        assert {r.source for r in rows} == {Enrollment.Source.PROGRAM}
        assert assignments.mentor_for(world["lea"], world["course"]) == world["mentor"]

    def test_running_it_again_changes_nothing(self, world, program):
        services.enroll_program(world["lea"], program["program"])
        steps = services.enroll_program(world["lea"], program["program"])
        assert [s.outcome for s in steps][:2] == [services.ALREADY, services.ALREADY]
        assert Enrollment.objects.count() == 2

    def test_a_course_added_later_reaches_existing_members_but_not_who_withdrew(
        self, make_role_user, world, program
    ):
        services.enroll_program(world["lea"], program["program"])
        services.enroll_program(world["oth"], program["program"])
        row = Enrollment.objects.get(user=world["oth"], course=world["course"])
        services.withdraw(row, "")
        extra = course_with(make_role_user, title="Added later")
        items = [(c.pk, True) for c in services.program_courses(program["program"])] + [
            (extra["course"].pk, True)
        ]
        services.save_program(
            program["program"], name="Cohort A", courses=items, by=world["trainer"]
        )
        counts = services.enroll_missing(program["program"], by=world["trainer"])
        assert counts["enrolled"] == 2  # both members, on the new course only
        assert (
            Enrollment.objects.get(user=world["oth"], course=world["course"]).state == "withdrawn"
        )
        assert Enrollment.objects.filter(course=extra["course"]).count() == 2

    def test_an_archived_program_cannot_enroll_anyone(self, world, program):
        services.archive_program(program["program"])
        with pytest.raises(Conflict, match="archived"):
            services.enroll_program(world["lea"], program["program"])

    def test_validation(self, world, program):
        with pytest.raises(EnrollmentError, match="name"):
            services.save_program(None, name="  ")
        with pytest.raises(Conflict, match="already a group"):
            services.save_program(None, name="cohort a")
        with pytest.raises(EnrollmentError, match="before it starts"):
            import datetime

            services.save_program(
                None,
                name="Dated",
                starts_on=datetime.date(2026, 5, 1),
                ends_on=datetime.date(2026, 4, 1),
            )
        with pytest.raises(EnrollmentError, match="only appear once"):
            services.save_program(
                program["program"],
                name="Cohort A",
                courses=[(world["course"].pk, True), (world["course"].pk, True)],
            )
        catalog.archive_course(world["course"])
        with pytest.raises(Conflict, match="archived course"):
            services.save_program(
                program["program"], name="Cohort A", courses=[(world["course"].pk, True)]
            )

    def test_an_archived_name_can_be_reused_but_not_restored_over_it(self, world, program):
        services.archive_program(program["program"])
        services.save_program(None, name="Cohort A")
        with pytest.raises(Conflict, match="taken this name"):
            services.restore_program(program["program"])
        assert Program.objects.count() == 2


class TestParsing:
    def test_header_blank_lines_delimiters_and_case(self):
        rows = services.parse_rows(
            "Email,Mentor\n\n  Ann@E.com , Mia@E.com\nbob@e.com;mia@e.com\n"
            '"cy@e.com"\tmia@e.com\ndee@e.com\n'
        )
        assert [(r.email, r.mentor_email) for r in rows] == [
            ("ann@e.com", "mia@e.com"),
            ("bob@e.com", "mia@e.com"),
            ("cy@e.com", "mia@e.com"),
            ("dee@e.com", ""),
        ]
        assert [r.line for r in rows] == [3, 4, 5, 6]

    def test_empty_and_oversized_lists_are_refused(self):
        with pytest.raises(EnrollmentError, match="empty"):
            services.parse_rows("  \n\n")
        with pytest.raises(EnrollmentError, match="empty"):
            services.parse_rows("email\n")
        with pytest.raises(EnrollmentError, match="more than"):
            services.parse_rows("\n".join(f"u{i}@e.com" for i in range(services.MAX_BULK_ROWS + 1)))
        with pytest.raises(EnrollmentError):
            services.parse_rows(None)  # type: ignore[arg-type]


class TestBulk:
    @pytest.fixture
    def people(self, make_role_user, world):
        out = dict(world)
        out["third"] = make_role_user(Role.Name.LEARNER, username="thd", email="third@e.com")
        out["staff"] = make_role_user(Role.Name.TRAINER, username="stf", email="staff@e.com")
        out["gone"] = make_role_user(Role.Name.LEARNER, username="gne", email="gone@e.com")
        User.objects.filter(pk=out["gone"].pk).update(is_active=False)
        return out

    def statuses(self, rows):
        return {r.email: r.status for r in rows}

    def test_the_preview_says_what_will_happen_to_every_row_and_changes_nothing(self, people):
        services.enroll(people["oth"], people["course"])
        before = User.objects.count()
        rows = services.bulk(
            "\n".join(
                [
                    "lea@e.com",
                    "oth@e.com",
                    "ghost@e.com",
                    "staff@e.com",
                    "gone@e.com",
                    "LEA@e.com",
                    "not-an-email",
                    "third@e.com,oth@e.com",  # a learner cannot be the mentor
                ]
            ),
            course=people["course"],
        )
        assert self.statuses([r for r in rows if r.status != "duplicate"]) == {
            "lea@e.com": "will_enroll",
            "oth@e.com": "already_enrolled",
            "ghost@e.com": "unknown_email",
            "staff@e.com": "not_a_learner",
            "gone@e.com": "inactive_user",
            "not-an-email": "bad_email",
            "third@e.com": "invalid_mentor",
        }
        assert [r.status for r in rows if r.email == "lea@e.com"] == ["will_enroll", "duplicate"]
        assert Enrollment.objects.count() == 1 and User.objects.count() == before

    def test_applying_does_exactly_what_the_preview_listed(self, people):
        text = "lea@e.com,mia@e.com\nthird@e.com\nghost@e.com\noth@e.com"
        services.enroll(people["oth"], people["course"])
        preview = services.bulk(text, course=people["course"])
        applied = services.bulk(text, course=people["course"], by=people["trainer"], apply=True)
        assert [r.status for r in preview] == [r.status for r in applied]
        assert {e.user.email for e in Enrollment.objects.all()} == {
            "lea@e.com",
            "third@e.com",
            "oth@e.com",
        }
        assert Enrollment.objects.get(user=people["lea"]).source == Enrollment.Source.IMPORT
        assert assignments.mentor_for(people["lea"], people["course"]) == people["mentor"]
        assert not User.objects.filter(email="ghost@e.com").exists()

    def test_applying_twice_enrolls_once(self, people):
        text = "lea@e.com\nthird@e.com"
        services.bulk(text, course=people["course"], apply=True)
        again = services.bulk(text, course=people["course"], apply=True)
        assert {r.status for r in again} == {"already_enrolled"}
        assert Enrollment.objects.count() == 2

    def test_a_withdrawn_person_is_offered_a_re_enrollment(self, people):
        row, _ = services.enroll(people["lea"], people["course"])
        services.withdraw(row, "")
        rows = services.bulk("lea@e.com", course=people["course"], apply=True)
        assert rows[0].status == "will_reactivate"
        assert Enrollment.objects.get(user=people["lea"]).state == Enrollment.State.ACTIVE

    def test_a_default_mentor_applies_unless_the_row_names_one(self, make_role_user, people):
        other = make_role_user(Role.Name.MENTOR, username="max", email="max@e.com")
        services.bulk(
            "lea@e.com\nthird@e.com,max@e.com",
            course=people["course"],
            default_mentor=people["mentor"],
            apply=True,
        )
        assert assignments.mentor_for(people["lea"], people["course"]) == people["mentor"]
        assert assignments.mentor_for(people["third"], people["course"]) == other

    def test_a_row_that_fails_does_not_undo_the_others(self, people, monkeypatch):
        real = services.enroll

        def flaky(user, *args, **kwargs):
            if user.email == "lea@e.com":
                raise EnrollmentError("Something broke.")
            return real(user, *args, **kwargs)

        monkeypatch.setattr(services, "enroll", flaky)
        rows = services.bulk("lea@e.com\nthird@e.com", course=people["course"], apply=True)
        assert self.statuses(rows) == {"lea@e.com": "failed", "third@e.com": "will_enroll"}
        assert rows[0].detail == "Something broke."
        assert [e.user.email for e in Enrollment.objects.all()] == ["third@e.com"]

    def test_a_program_is_a_target_too(self, make_role_user, people):
        other = course_with(make_role_user, title="Second")
        program = services.save_program(
            None, name="P", courses=[(people["course"].pk, True), (other["course"].pk, True)]
        )
        services.enroll(people["lea"], people["course"])
        rows = services.bulk("lea@e.com\nthird@e.com", program=program, apply=True)
        assert self.statuses(rows) == {"lea@e.com": "will_enroll", "third@e.com": "will_enroll"}
        assert Enrollment.objects.filter(user=people["lea"]).count() == 2
        assert Enrollment.objects.filter(user=people["third"]).count() == 2
        lea_other = Enrollment.objects.get(user=people["lea"], course=other["course"])
        assert lea_other.source == Enrollment.Source.PROGRAM

    def test_a_target_is_required_and_a_program_needs_courses(self, people):
        with pytest.raises(EnrollmentError, match="Choose a course or a group"):
            services.bulk("lea@e.com")
        empty = services.save_program(None, name="Empty")
        with pytest.raises(Conflict, match="no courses"):
            services.bulk("lea@e.com", program=empty)

    def test_an_unreleased_course_leaves_nothing_to_enroll(self, make_role_user, people):
        draft = course_with(make_role_user, title="Draft", publish=False)
        rows = services.bulk("lea@e.com", course=draft["course"])
        assert rows[0].status == "nothing_to_enroll" and "no published version" in rows[0].detail
