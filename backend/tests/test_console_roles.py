"""Admin Console → Roles: the role × capability matrix and its safeguards."""

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.rbac import KNOWN_ACTIONS, ROLE_PERMISSIONS, capabilities_for
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def url(name, *args):
    return reverse(f"console_api:{name}", args=args)


@pytest.fixture
def people(make_role_user):
    return {
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="trn", email="trn@example.com"),
        "learner": make_role_user(Role.Name.LEARNER, username="lrn", email="lrn@example.com"),
    }


@pytest.fixture
def seeded(people):
    """make_role_user only attaches permissions to the roles it creates; seed all."""
    from django.core.management import call_command

    call_command("seed_roles")


def matrix(client, who):
    client.force_login(who)
    return client.get(url("roles")).json()


def put(client, role, permissions):
    return client.put(
        url("role-permissions", Role.objects.get(name=role).pk),
        {"permissions": permissions},
        content_type="application/json",
    )


class TestMatrix:
    def test_lists_every_role_with_what_it_may_do_and_how_many_hold_it(
        self, client, people, seeded
    ):
        body = matrix(client, people["admin"])
        roles = {r["name"]: r for r in body["roles"]}
        assert set(roles) == {"learner", "trainer", "mentor", "admin"}
        assert roles["trainer"]["permissions"] == sorted(ROLE_PERMISSIONS["trainer"])
        assert roles["learner"]["permissions"] == []
        assert roles["admin"]["members"] == 1 and roles["trainer"]["members"] == 1
        assert roles["admin"]["label"] == "Admin"

    def test_the_admin_role_reports_what_it_must_keep(self, client, people, seeded):
        roles = {r["name"]: r for r in matrix(client, people["admin"])["roles"]}
        assert roles["admin"]["locked"] == ["accounts.manage_users", "accounts.manage_roles"]
        assert roles["trainer"]["locked"] == []

    def test_describes_every_action_in_plain_words(self, client, people, seeded):
        actions = matrix(client, people["admin"])["actions"]
        assert [a["key"] for a in actions] == list(KNOWN_ACTIONS)
        assert all(a["label"] and a["description"] for a in actions)

    def test_members_count_only_active_people(self, client, people, seeded):
        people["trainer"].is_active = False
        people["trainer"].save()
        roles = {r["name"]: r for r in matrix(client, people["admin"])["roles"]}
        assert roles["trainer"]["members"] == 0


class TestChange:
    def test_grants_and_revokes_and_the_effect_is_immediate(self, client, people, seeded):
        client.force_login(people["admin"])
        assert "audit.view_audit" not in capabilities_for(people["trainer"])
        response = put(client, "trainer", [*ROLE_PERMISSIONS["trainer"], "audit.view_audit"])
        assert response.status_code == 200
        assert "audit.view_audit" in response.json()["permissions"]
        assert "audit.view_audit" in capabilities_for(people["trainer"])
        # …and the trainer can now open the audit log.
        client.force_login(people["trainer"])
        assert client.get(url("audit")).status_code == 200

        client.force_login(people["admin"])
        put(client, "trainer", ["catalog.author_content"])
        assert capabilities_for(people["trainer"]) == ["catalog.author_content"]

    def test_logs_before_and_after_and_skips_no_ops(self, client, people, seeded):
        client.force_login(people["admin"])
        put(client, "trainer", ROLE_PERMISSIONS["trainer"])  # nothing changes
        assert not AuditLog.objects.exists()
        put(client, "trainer", ["catalog.author_content"])
        entry = AuditLog.objects.get(action="roles.set_permissions")
        assert entry.target_label == "Trainer"
        assert entry.changes == {
            "before": sorted(ROLE_PERMISSIONS["trainer"]),
            "after": ["catalog.author_content"],
        }

    def test_admins_always_keep_the_power_to_undo_a_mistake(self, client, people, seeded):
        client.force_login(people["admin"])
        response = put(client, "admin", ["catalog.author_content", "accounts.manage_users"])
        assert response.status_code == 400 and "Manage roles" in response.json()["detail"]
        assert "accounts.manage_roles" in capabilities_for(people["admin"])

    def test_admins_can_still_gain_or_lose_the_rest(self, client, people, seeded):
        client.force_login(people["admin"])
        keep = ["accounts.manage_users", "accounts.manage_roles"]
        assert put(client, "admin", keep).status_code == 200
        assert put(client, "admin", [*keep, "audit.view_audit"]).status_code == 200

    def test_unknown_permissions_are_refused_so_nothing_arbitrary_can_be_granted(
        self, client, people, seeded
    ):
        client.force_login(people["admin"])
        for bad in (["auth.delete_user"], ["nonsense"], ["catalog.author_content", "x.y"]):
            assert put(client, "trainer", bad).status_code == 400
        assert capabilities_for(people["trainer"]) == [
            a for a in KNOWN_ACTIONS if a in ROLE_PERMISSIONS["trainer"]
        ]

    def test_permissions_outside_the_catalogue_are_left_alone(self, client, people, seeded):
        extra = Permission.objects.get(content_type__app_label="accounts", codename="view_user")
        trainer = Role.objects.get(name="trainer")
        trainer.permissions.add(extra)
        client.force_login(people["admin"])
        put(client, "trainer", ["catalog.author_content"])
        assert extra in trainer.permissions.all()

    def test_unknown_role_is_404(self, client, people, seeded):
        client.force_login(people["admin"])
        response = client.put(
            url("role-permissions", 99999), {"permissions": []}, content_type="application/json"
        )
        assert response.status_code == 404

    def test_only_those_who_manage_roles_may_change_them(self, client, people, seeded):
        client.force_login(people["trainer"])
        assert put(client, "trainer", list(KNOWN_ACTIONS)).status_code == 403
        assert capabilities_for(people["trainer"]) == [
            a for a in KNOWN_ACTIONS if a in ROLE_PERMISSIONS["trainer"]
        ]


def post_json(client, path, data):
    return client.post(path, data, content_type="application/json")


class TestCustomRoles:
    def create(self, client, who, name, permissions=None):
        client.force_login(who)
        body = {"name": name}
        if permissions is not None:
            body["permissions"] = permissions
        return post_json(client, url("role-create"), body)

    def test_an_admin_can_add_a_role_and_choose_what_it_may_do(self, client, people, seeded):
        response = self.create(
            client, people["admin"], "Senior Support", ["progress.view_results", "audit.view_audit"]
        )
        assert response.status_code == 201
        body = response.json()
        assert body["label"] == "Senior Support" and body["name"] == "senior_support"
        assert body["builtin"] is False and body["members"] == 0 and body["locked"] == []
        assert body["permissions"] == ["audit.view_audit", "progress.view_results"]
        role = Role.objects.get(name="senior_support")
        assert str(role) == "Senior Support" and not role.is_builtin

    def test_the_new_role_shows_up_in_the_matrix_and_the_pickers(self, client, people, seeded):
        self.create(client, people["admin"], "Senior Support")
        roles = {r["name"]: r for r in client.get(url("roles")).json()["roles"]}
        assert roles["senior_support"]["label"] == "Senior Support"
        assert roles["admin"]["builtin"] is True
        options = client.get(url("role-options")).json()["results"]
        assert {"name": "senior_support", "label": "Senior Support", "builtin": False} in options
        assert [o["name"] for o in options[:4]] == ["learner", "trainer", "mentor", "admin"]

    def test_someone_given_the_new_role_gets_exactly_its_abilities(self, client, people, seeded):
        self.create(client, people["admin"], "Auditor", ["audit.view_audit"])
        put_roles = client.put(
            url("user-roles", people["learner"].pk),
            {"roles": ["auditor"]},
            content_type="application/json",
        )
        assert put_roles.status_code == 200
        assert capabilities_for(people["learner"]) == ["audit.view_audit"]
        client.force_login(people["learner"])
        assert client.get(url("audit")).status_code == 200
        assert client.get(url("users")).status_code == 403

    def test_its_permissions_can_be_changed_like_any_other_role(self, client, people, seeded):
        role_id = self.create(client, people["admin"], "Auditor").json()["id"]
        client.force_login(people["admin"])
        response = client.put(
            url("role-permissions", role_id),
            {"permissions": ["progress.view_results"]},
            content_type="application/json",
        )
        assert response.json()["permissions"] == ["progress.view_results"]

    def test_creation_is_logged(self, client, people, seeded):
        self.create(client, people["admin"], "Auditor", ["audit.view_audit"])
        entry = AuditLog.objects.get(action="roles.create")
        assert entry.target_label == "Auditor"
        assert entry.changes == {"name": "auditor", "permissions": ["audit.view_audit"]}

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("", "name"),
            ("   ", "name"),
            ("Admin", "built-in"),
            ("Mentor", "built-in"),
            ("!!!", "letters and numbers"),
            ("x" * 70, "too long"),
        ],
    )
    def test_bad_names_are_refused_in_plain_words(self, client, people, seeded, name, message):
        response = self.create(client, people["admin"], name)
        assert response.status_code == 400
        assert message in response.json()["detail"].lower()

    def test_duplicates_are_refused(self, client, people, seeded):
        self.create(client, people["admin"], "Auditor")
        assert self.create(client, people["admin"], "auditor").status_code == 400
        assert self.create(client, people["admin"], "AUDITOR").status_code == 400
        assert Role.objects.filter(name="auditor").count() == 1

    def test_a_role_with_unknown_permissions_is_not_created(self, client, people, seeded):
        response = self.create(client, people["admin"], "Sneaky", ["auth.delete_user"])
        assert response.status_code == 400
        assert not Role.objects.filter(name="sneaky").exists()

    def test_only_those_who_manage_roles_may_add_one(self, client, people, seeded):
        assert self.create(client, people["trainer"], "Auditor").status_code == 403
        assert self.create(client, people["learner"], "Auditor").status_code == 403
        client.logout()
        assert post_json(client, url("role-create"), {"name": "Auditor"}).status_code == 403
        assert not Role.objects.filter(name="auditor").exists()


class TestRenameAndDelete:
    @pytest.fixture
    def auditor(self, client, people, seeded):
        client.force_login(people["admin"])
        return post_json(client, url("role-create"), {"name": "Auditor"}).json()

    def patch(self, client, role_id, name):
        return client.patch(url("role", role_id), {"name": name}, content_type="application/json")

    def test_a_custom_role_can_be_renamed_and_the_change_is_logged(self, client, people, auditor):
        response = self.patch(client, auditor["id"], "Compliance reviewer")
        assert response.status_code == 200 and response.json()["label"] == "Compliance reviewer"
        assert response.json()["name"] == "auditor"  # the key stays stable
        entry = AuditLog.objects.get(action="roles.rename")
        assert entry.changes == {"before": "Auditor", "after": "Compliance reviewer"}

    def test_renaming_to_the_same_name_logs_nothing(self, client, people, auditor):
        self.patch(client, auditor["id"], "Auditor")
        assert not AuditLog.objects.filter(action="roles.rename").exists()

    def test_built_in_roles_cannot_be_renamed_or_deleted(self, client, people, auditor):
        for name in ("learner", "trainer", "mentor", "admin"):
            role = Role.objects.get(name=name)
            assert self.patch(client, role.pk, "Something else").status_code == 400
            assert client.delete(url("role", role.pk)).status_code == 400
            assert Role.objects.filter(name=name).exists()

    def test_a_name_already_in_use_is_refused(self, client, people, auditor):
        other = post_json(client, url("role-create"), {"name": "Reviewer"}).json()
        assert self.patch(client, other["id"], "auditor").status_code == 400

    def test_an_unused_custom_role_can_be_deleted_and_it_is_logged(self, client, people, auditor):
        assert client.delete(url("role", auditor["id"])).status_code == 204
        assert not Role.objects.filter(name="auditor").exists()
        entry = AuditLog.objects.get(action="roles.delete")
        assert entry.target_label == "Auditor" and entry.changes["name"] == "auditor"

    def test_a_role_people_still_hold_cannot_be_deleted(self, client, people, auditor):
        client.put(
            url("user-roles", people["learner"].pk),
            {"roles": ["auditor"]},
            content_type="application/json",
        )
        response = client.delete(url("role", auditor["id"]))
        assert response.status_code == 409
        assert "1 person holds this role" in response.json()["detail"]
        assert Role.objects.filter(name="auditor").exists()

    def test_unknown_role_is_404(self, client, people, auditor):
        assert self.patch(client, 99999, "X").status_code == 404
        assert client.delete(url("role", 99999)).status_code == 404

    def test_only_those_who_manage_roles_may(self, client, people, auditor):
        client.force_login(people["trainer"])
        assert self.patch(client, auditor["id"], "Hacked").status_code == 403
        assert client.delete(url("role", auditor["id"])).status_code == 403
        assert Role.objects.get(pk=auditor["id"]).display_label == "Auditor"


class TestRoleOptions:
    def test_people_who_manage_users_can_see_the_roles_without_managing_them(
        self, client, people, seeded
    ):
        mentor_role = Role.objects.get(name="mentor")
        mentor_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="manage_users")
        )
        client.force_login(people["learner"])
        assert client.get(url("role-options")).status_code == 403
        client.force_login(people["admin"])
        assert client.get(url("role-options")).status_code == 200

    def test_anonymous_and_ordinary_users_are_refused(self, client, people, seeded):
        assert client.get(url("role-options")).status_code == 403
        client.force_login(people["trainer"])
        assert client.get(url("role-options")).status_code == 403
