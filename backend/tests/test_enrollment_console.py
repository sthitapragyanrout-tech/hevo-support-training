"""The enrollment Console API: who may use it, what it does, what it records."""

import json

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.enrollment import services
from apps.enrollment.models import Enrollment, Program
from apps.manual_sim import assignments
from tests.enrollment_helpers import course_with, publish_next

pytestmark = [pytest.mark.django_db, pytest.mark.real_enrollment]


@pytest.fixture
def world(make_role_user):
    w = course_with(make_role_user)
    w["lea"] = make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com")
    w["oth"] = make_role_user(Role.Name.LEARNER, username="oth", email="oth@e.com")
    w["mentor"] = make_role_user(Role.Name.MENTOR, username="mia", email="mia@e.com")
    w["trainer"] = make_role_user(Role.Name.TRAINER, username="tom", email="tom@e.com")
    w["root"] = make_role_user(Role.Name.ADMIN, username="ada", email="ada@e.com")
    return w


def u(name, *args):
    return reverse(f"console_api:{name}", args=args)


def call(client, user, method, url, data=None):
    client.force_login(user)
    if method == "get" or data is None:
        return getattr(client, method)(url)
    return getattr(client, method)(url, json.dumps(data), content_type="application/json")


def enroll(client, user, people, **extra):
    return call(
        client, user, "post", u("enrollments"), {"user_ids": [p.pk for p in people], **extra}
    )


def actions():
    return list(AuditLog.objects.order_by("id").values_list("action", flat=True))


ENDPOINTS = [
    ("get", "enrollments", ()),
    ("post", "enrollments", ()),
    ("get", "enrollment-options", ()),
    ("get", "enrollment-people", ()),
    ("post", "enrollment-bulk", ()),
    ("post", "enrollment-withdraw", (1,)),
    ("post", "enrollment-reenroll", (1,)),
    ("post", "enrollment-mentor", (1,)),
    ("post", "enrollment-group", (1,)),
    ("get", "enrollment-modules", (1,)),
    ("post", "enrollment-modules", (1,)),
    ("get", "programs", ()),
    ("post", "programs", ()),
    ("get", "program", (1,)),
    ("put", "program", (1,)),
    ("post", "program-archive", (1,)),
    ("post", "program-restore", (1,)),
    ("post", "program-enroll-missing", (1,)),
]


class TestWhoMayUseIt:
    @pytest.mark.parametrize("method,name,args", ENDPOINTS)
    @pytest.mark.parametrize("who", ["lea", "mentor", "author"])
    def test_learners_and_mentors_and_even_authors_without_the_permission_are_refused(
        self, client, world, method, name, args, who
    ):
        user = world[who]
        if who == "author":  # a trainer who has lost the permission
            from django.contrib.auth.models import Permission

            role = Role.objects.get(name="trainer")
            role.permissions.remove(
                Permission.objects.get(
                    content_type__app_label="enrollment", codename="manage_enrollments"
                )
            )
        response = call(client, user, method, u(name, *args), {})
        assert response.status_code == 403, response.content

    @pytest.mark.parametrize("method,name,args", ENDPOINTS)
    def test_signed_out_is_refused(self, client, method, name, args):
        response = getattr(client, method)(u(name, *args))
        assert response.status_code in (401, 403)

    @pytest.mark.parametrize("who", ["trainer", "root"])
    def test_trainers_and_admins_are_let_in(self, client, world, who):
        assert call(client, world[who], "get", u("enrollments")).status_code == 200
        assert call(client, world[who], "get", u("programs")).status_code == 200


class TestOptionsAndPeople:
    def test_options_list_enrollable_courses_programs_and_mentors(
        self, client, make_role_user, world
    ):
        course_with(make_role_user, title="Unreleased", publish=False)
        services.save_program(None, name="P", courses=[(world["course"].pk, True)])
        body = call(client, world["trainer"], "get", u("enrollment-options")).json()
        assert [c["title"] for c in body["courses"]] == ["Course"]
        assert [p["name"] for p in body["programs"]] == ["P"]
        assert body["programs"][0]["course_ids"] == [world["course"].pk]
        # Anyone who may rate simulations can be a mentor: the mentor, and trainers/admins.
        assert "mia@e.com" in [m["email"] for m in body["mentors"]]
        assert "lea@e.com" not in [m["email"] for m in body["mentors"]]

    def test_the_picker_finds_learners_only_and_marks_who_is_already_on(self, client, world):
        services.enroll(world["lea"], world["course"])
        body = call(
            client,
            world["trainer"],
            "get",
            u("enrollment-people") + f"?course={world['course'].pk}",
        ).json()
        found = {r["email"]: r["on_course"] for r in body["results"]}
        assert found == {"lea@e.com": True, "oth@e.com": False}
        body = call(client, world["trainer"], "get", u("enrollment-people") + "?search=OTH").json()
        assert [r["email"] for r in body["results"]] == ["oth@e.com"]


class TestEnrolling:
    def test_enroll_people_with_a_mentor_and_it_is_audited(self, client, world):
        response = enroll(
            client,
            world["trainer"],
            [world["lea"], world["oth"]],
            course_id=world["course"].pk,
            mentor_id=world["mentor"].pk,
        )
        assert response.status_code == 200, response.content
        results = response.json()["results"]
        assert [r["outcome"] for r in results] == ["enrolled", "enrolled"]
        assert results[0]["enrollment"]["mentor"]["email"] == "mia@e.com"
        assert results[0]["enrollment"]["version"] == {
            "id": world["version"].pk,
            "number": 1,
            "latest_number": 1,
            "older": False,
        }
        assert actions() == ["enrollments.enroll", "enrollments.enroll"]
        entry = AuditLog.objects.order_by("id").first()
        assert entry.actor == world["trainer"] and "lea@e.com" in entry.target_label

    def test_enrolling_again_is_reported_and_not_audited_twice(self, client, world):
        enroll(client, world["trainer"], [world["lea"]], course_id=world["course"].pk)
        again = enroll(client, world["trainer"], [world["lea"]], course_id=world["course"].pk)
        assert again.json()["results"][0]["outcome"] == "already"
        assert actions() == ["enrollments.enroll"]

    def test_a_person_who_cannot_be_enrolled_is_reported_and_the_rest_go_ahead(
        self, client, make_role_user, world
    ):
        User.objects.filter(pk=world["oth"].pk).update(is_active=False)
        response = enroll(
            client, world["trainer"], [world["oth"], world["lea"]], course_id=world["course"].pk
        )
        outcomes = [r["outcome"] for r in response.json()["results"]]
        assert outcomes == ["failed", "enrolled"]
        assert "deactivated" in response.json()["results"][0]["detail"]

    def test_a_program_enrolls_on_each_of_its_courses(self, client, make_role_user, world):
        other = course_with(make_role_user, title="Second")
        program = services.save_program(
            None, name="P", courses=[(world["course"].pk, True), (other["course"].pk, True)]
        )
        response = enroll(client, world["trainer"], [world["lea"]], program_id=program.pk)
        result = response.json()["results"][0]
        assert result["outcome"] == "program"
        assert [c["outcome"] for c in result["courses"]] == ["enrolled", "enrolled"]
        assert Enrollment.objects.filter(user=world["lea"], program=program).count() == 2

    @pytest.mark.parametrize(
        "data,message",
        [
            ({}, "Choose a course or a group"),
            ({"course_id": 1, "program_id": 1}, "Choose a course or a group"),
            ({"course_id": True}, "must be a number"),
            ({"course_id": "x"}, "must be a number"),
        ],
    )
    def test_bad_targets_are_refused_plainly(self, client, world, data, message):
        response = enroll(client, world["trainer"], [world["lea"]], **data)
        assert response.status_code == 400 and message in response.json()["detail"]

    def test_bad_people_lists_are_refused(self, client, world):
        for bad in ([], "lea", [True], [1.5], [None]):
            response = call(
                client,
                world["trainer"],
                "post",
                u("enrollments"),
                {"user_ids": bad, "course_id": world["course"].pk},
            )
            assert response.status_code == 400, bad
        missing = enroll(client, world["trainer"], [world["lea"]], course_id=world["course"].pk)
        assert missing.status_code == 200
        response = call(
            client,
            world["trainer"],
            "post",
            u("enrollments"),
            {"user_ids": [999999], "course_id": world["course"].pk},
        )
        assert response.status_code == 404
        assert (
            call(
                client,
                world["trainer"],
                "post",
                u("enrollments"),
                {"user_ids": [1], "course_id": 999999},
            ).status_code
            == 404
        )

    def test_a_course_nobody_can_enroll_on_is_a_plain_message(self, client, make_role_user, world):
        draft = course_with(make_role_user, title="Draft", publish=False)
        response = enroll(client, world["trainer"], [world["lea"]], course_id=draft["course"].pk)
        result = response.json()["results"][0]
        assert result["outcome"] == "failed" and "no published version" in result["detail"]


class TestTheList:
    @pytest.fixture
    def filled(self, make_role_user, world):
        other = course_with(make_role_user, title="Other course")
        services.enroll(world["lea"], world["course"], mentor=world["mentor"])
        services.enroll(world["oth"], world["course"])
        services.enroll(world["lea"], other["course"])
        world["other"] = other
        return world

    def rows(self, client, world, query=""):
        body = call(client, world["trainer"], "get", u("enrollments") + query).json()
        return body["results"], body

    def test_lists_active_rows_with_who_what_version_and_mentor(self, client, filled):
        rows, body = self.rows(client, filled)
        assert body["count"] == 3
        mine = next(
            r
            for r in rows
            if r["user"]["email"] == "lea@e.com" and r["course"]["title"] == "Course"
        )
        assert mine["mentor"]["email"] == "mia@e.com" and mine["state"] == "active"
        assert mine["version"]["number"] == 1 and mine["program"] is None

    def test_filters(self, client, filled):
        course = filled["course"].pk
        assert len(self.rows(client, filled, f"?course={course}")[0]) == 2
        assert [r["user"]["email"] for r in self.rows(client, filled, "?search=oth")[0]] == [
            "oth@e.com"
        ]
        assert len(self.rows(client, filled, f"?mentor={filled['mentor'].pk}")[0]) == 1
        row = Enrollment.objects.get(user=filled["oth"])
        services.withdraw(row, "x")
        assert len(self.rows(client, filled)[0]) == 2
        assert len(self.rows(client, filled, "?state=withdrawn")[0]) == 1
        assert len(self.rows(client, filled, "?state=all")[0]) == 3

    def test_on_an_older_version_is_flagged_and_filterable(self, client, filled):
        publish_next(filled)
        rows, _ = self.rows(client, filled)
        mine = [r for r in rows if r["course"]["title"] == "Course"]
        assert all(r["version"]["older"] and r["version"]["latest_number"] == 2 for r in mine)
        older, _ = self.rows(client, filled, "?older=1")
        assert len(older) == 2
        services.enroll(filled["root"], filled["course"])  # pinned on v2: not "older"
        assert len(self.rows(client, filled, "?older=1")[0]) == 2

    def test_pages(self, client, filled):
        body = call(client, filled["trainer"], "get", u("enrollments") + "?page_size=2").json()
        assert len(body["results"]) == 2 and body["pages"] == 2


class TestOneRow:
    def test_withdraw_then_reenroll_with_audit(self, client, world):
        row, _ = services.enroll(world["lea"], world["course"], mentor=world["mentor"])
        gone = call(
            client, world["trainer"], "post", u("enrollment-withdraw", row.pk), {"reason": "Left"}
        )
        assert gone.status_code == 200 and gone.json()["state"] == "withdrawn"
        assert gone.json()["mentor"] is None and gone.json()["withdrawn_reason"] == "Left"
        again = call(client, world["trainer"], "post", u("enrollment-withdraw", row.pk), {})
        assert again.status_code == 409
        back = call(client, world["trainer"], "post", u("enrollment-reenroll", row.pk), {})
        assert back.status_code == 200 and back.json()["state"] == "active"
        assert actions() == ["enrollments.withdraw", "enrollments.reenroll"]

    def test_change_the_mentor_and_clear_it(self, client, world):
        row, _ = services.enroll(world["lea"], world["course"])
        done = call(
            client,
            world["trainer"],
            "post",
            u("enrollment-mentor", row.pk),
            {"mentor_id": world["mentor"].pk},
        )
        assert done.json()["mentor"]["email"] == "mia@e.com"
        cleared = call(client, world["trainer"], "post", u("enrollment-mentor", row.pk), {})
        assert cleared.json()["mentor"] is None
        entry = AuditLog.objects.filter(action="enrollments.mentor").order_by("id").first()
        assert entry.changes == {"from": "shared pool", "to": "mia@e.com"}
        bad = call(
            client,
            world["trainer"],
            "post",
            u("enrollment-mentor", row.pk),
            {"mentor_id": world["oth"].pk},
        )
        assert bad.status_code == 400
        assert assignments.mentor_for(world["lea"], world["course"]) is None

    def test_set_change_and_clear_the_group_with_audit(self, client, make_role_user, world):
        other = course_with(make_role_user, title="Other")
        l1 = Program.objects.create(name="L1")
        l1.items.create(course=world["course"])
        l2 = Program.objects.create(name="L2")
        l2.items.create(course=world["course"])
        elsewhere = Program.objects.create(name="Elsewhere")
        elsewhere.items.create(course=other["course"])
        row, _ = services.enroll(world["lea"], world["course"])
        url = u("enrollment-group", row.pk)

        done = call(client, world["trainer"], "post", url, {"program_id": l1.pk})
        assert done.status_code == 200 and done.json()["program"]["name"] == "L1"
        moved = call(client, world["trainer"], "post", url, {"program_id": l2.pk})
        assert moved.json()["program"]["name"] == "L2"
        cleared = call(client, world["trainer"], "post", url, {"program_id": None})
        assert cleared.json()["program"] is None

        wrong = call(client, world["trainer"], "post", url, {"program_id": elsewhere.pk})
        assert wrong.status_code == 400 and "include this course" in wrong.json()["detail"]
        from django.utils import timezone

        l1.archived_at = timezone.now()
        l1.save()
        assert call(client, world["trainer"], "post", url, {"program_id": l1.pk}).status_code == 409
        assert call(client, world["trainer"], "post", url, {"program_id": 99999}).status_code == 404
        row.refresh_from_db()
        assert row.program is None
        changes = list(
            AuditLog.objects.filter(action="enrollments.group")
            .order_by("id")
            .values_list("changes", flat=True)
        )
        assert changes == [
            {"from": "no group", "to": "L1"},
            {"from": "L1", "to": "L2"},
            {"from": "L2", "to": "no group"},
        ]
        # Only a label: what the learner can open is unchanged.
        assert Enrollment.objects.get(pk=row.pk).version_id == row.version_id

    def test_unknown_rows_are_404(self, client, world):
        for name in (
            "enrollment-withdraw",
            "enrollment-reenroll",
            "enrollment-mentor",
            "enrollment-group",
        ):
            assert call(client, world["trainer"], "post", u(name, 99999), {}).status_code == 404


class TestBulkEndpoint:
    def body(self, world, **extra):
        return {
            "text": "lea@e.com,mia@e.com\nghost@e.com\noth@e.com",
            "course_id": world["course"].pk,
            **extra,
        }

    def test_preview_changes_nothing_and_apply_does_what_it_said(self, client, world):
        preview = call(client, world["trainer"], "post", u("enrollment-bulk"), self.body(world))
        assert preview.status_code == 200
        body = preview.json()
        assert body["applied"] is False
        assert body["summary"] == {"will_enroll": 2, "unknown_email": 1}
        assert not Enrollment.objects.exists() and not AuditLog.objects.exists()
        rows = {r["email"]: r for r in body["rows"]}
        assert rows["ghost@e.com"]["label"] == "No account with this email"
        assert rows["lea@e.com"]["user"]["email"] == "lea@e.com"

        done = call(
            client, world["trainer"], "post", u("enrollment-bulk"), self.body(world, apply=True)
        ).json()
        assert done["applied"] is True and done["summary"] == body["summary"]
        assert Enrollment.objects.count() == 2
        assert actions() == ["enrollments.enroll", "enrollments.enroll"]
        assert AuditLog.objects.order_by("id").first().changes["via"] == "list"
        assert assignments.mentor_for(world["lea"], world["course"]) == world["mentor"]

    def test_only_apply_true_applies(self, client, world):
        call(client, world["trainer"], "post", u("enrollment-bulk"), self.body(world, apply="true"))
        assert not Enrollment.objects.exists()

    def test_bad_input(self, client, world):
        for data in (
            {"course_id": world["course"].pk},
            {"text": "a@e.com"},
            {"text": 5, "course_id": world["course"].pk},
        ):
            assert (
                call(client, world["trainer"], "post", u("enrollment-bulk"), data).status_code
                == 400
            )


class TestPrograms:
    def test_create_edit_list_archive_restore(self, client, make_role_user, world):
        other = course_with(make_role_user, title="Second")
        created = call(
            client,
            world["trainer"],
            "post",
            u("programs"),
            {
                "name": "Cohort A",
                "description": "March hires",
                "starts_on": "2026-03-01",
                "ends_on": "2026-04-01",
                "courses": [
                    {"course_id": world["course"].pk},
                    {"course_id": other["course"].pk, "required": False},
                ],
            },
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert [c["title"] for c in body["courses"]] == ["Course", "Second"]
        assert [c["required"] for c in body["courses"]] == [True, False]
        assert body["starts_on"] == "2026-03-01" and body["members"] == 0

        pk = body["id"]
        edited = call(
            client,
            world["trainer"],
            "put",
            u("program", pk),
            {"name": "Cohort A (March)", "courses": [{"course_id": other["course"].pk}]},
        )
        assert edited.status_code == 200
        assert [c["title"] for c in edited.json()["courses"]] == ["Second"]

        listed = call(client, world["trainer"], "get", u("programs")).json()["results"]
        assert [p["name"] for p in listed] == ["Cohort A (March)"]
        assert call(client, world["trainer"], "post", u("program-archive", pk), {}).json()[
            "archived"
        ]
        assert call(client, world["trainer"], "get", u("programs")).json()["results"] == []
        archived = call(client, world["trainer"], "get", u("programs") + "?archived=1").json()
        assert len(archived["results"]) == 1
        assert not call(client, world["trainer"], "post", u("program-restore", pk), {}).json()[
            "archived"
        ]
        assert actions() == [
            "programs.create",
            "programs.update",
            "programs.archive",
            "programs.restore",
        ]

    @pytest.mark.parametrize(
        "data,message",
        [
            ({"name": ""}, "name"),
            ({"name": "P", "starts_on": "soon"}, "Dates must look like"),
            ({"name": "P", "courses": "x"}, "must be a list"),
            ({"name": "P", "courses": [{"title": "x"}]}, "needs a course_id"),
            ({"name": "P", "courses": [{"course_id": 99999}]}, "doesn’t exist"),
        ],
    )
    def test_validation(self, client, world, data, message):
        response = call(client, world["trainer"], "post", u("programs"), data)
        assert response.status_code in (400, 404) and message in response.json()["detail"]
        assert not Program.objects.exists()

    def test_a_duplicate_name_is_a_conflict(self, client, world):
        call(client, world["trainer"], "post", u("programs"), {"name": "A"})
        again = call(client, world["trainer"], "post", u("programs"), {"name": "a"})
        assert again.status_code == 409

    def test_catching_up_members_on_a_new_course(self, client, make_role_user, world):
        program = services.save_program(None, name="P", courses=[(world["course"].pk, True)])
        services.enroll_program(world["lea"], program)
        extra = course_with(make_role_user, title="Added")
        call(
            client,
            world["trainer"],
            "put",
            u("program", program.pk),
            {
                "name": "P",
                "courses": [{"course_id": world["course"].pk}, {"course_id": extra["course"].pk}],
            },
        )
        done = call(client, world["trainer"], "post", u("program-enroll-missing", program.pk), {})
        assert done.status_code == 200 and done.json()["enrolled"] == 1
        assert done.json()["program"]["members"] == 1
        assert "programs.enroll_missing" in actions()
