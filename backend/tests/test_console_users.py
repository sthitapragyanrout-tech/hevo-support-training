"""Admin Console → Users: find, create, edit, deactivate, reset password,
unlock, assign roles. Permissions, safeguards and the audit trail."""

from datetime import timedelta

import pytest
from axes.models import AccessAttempt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()


def url(name, *args):
    return reverse(f"console_api:{name}", args=args)


def put(client, path, data):
    return client.put(path, data, content_type="application/json")


def patch(client, path, data):
    return client.patch(path, data, content_type="application/json")


def post(client, path, data=None):
    return client.post(path, data or {}, content_type="application/json")


@pytest.fixture
def people(make_role_user):
    return {
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com"),
        "admin2": make_role_user(Role.Name.ADMIN, username="adm2", email="adm2@example.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="trn", email="trn@example.com"),
        "mentor": make_role_user(Role.Name.MENTOR, username="mnt", email="mnt@example.com"),
        "ann": make_role_user(
            Role.Name.LEARNER,
            username="ann",
            email="ann@example.com",
            first_name="Ann",
            last_name="Ames",
            employee_id="E1",
        ),
        "bob": make_role_user(Role.Name.LEARNER, username="bob", email="bob@example.com"),
    }


def as_user(client, user):
    client.force_login(user)
    return client


_ips = iter(f"10.0.{i // 250}.{i % 250 + 1}" for i in range(10_000))


def lock(username, failures=5, ago=timedelta(minutes=1)):
    attempt = AccessAttempt.objects.create(
        username=username, ip_address=next(_ips), failures_since_start=failures
    )
    # `attempt_time` is stamped on creation; back-date it afterwards.
    AccessAttempt.objects.filter(pk=attempt.pk).update(attempt_time=timezone.now() - ago)
    return attempt


class TestPermissions:
    def endpoints(self, people):
        ann = people["ann"].pk
        return [
            ("get", url("users")),
            ("post", url("users")),
            ("get", url("user", ann)),
            ("patch", url("user", ann)),
            ("post", url("set-password", ann)),
            ("post", url("unlock", ann)),
            ("put", url("user-roles", ann)),
            ("get", url("roles")),
            ("put", url("role-permissions", Role.objects.first().pk)),
        ]

    @pytest.mark.parametrize("who", [None, "ann", "mentor", "trainer"])
    def test_only_admins_get_anywhere(self, client, people, who):
        if who:
            as_user(client, people[who])
        for method, path in self.endpoints(people):
            response = (
                getattr(client, method)(path, {}, content_type="application/json")
                if method
                in (
                    "post",
                    "put",
                    "patch",
                )
                else getattr(client, method)(path)
            )
            assert response.status_code == 403, (method, path)
        assert User.objects.get(pk=people["ann"].pk).is_active

    def test_managing_users_alone_does_not_allow_changing_roles(self, client, people):
        mentor_role = Role.objects.get(name=Role.Name.MENTOR)
        mentor_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="manage_users")
        )
        as_user(client, people["mentor"])
        assert client.get(url("users")).status_code == 200
        assert (
            put(client, url("user-roles", people["ann"].pk), {"roles": ["trainer"]}).status_code
            == 403
        )
        assert client.get(url("roles")).status_code == 403
        created = post(client, url("users"), {"email": "n@example.com", "roles": ["trainer"]})
        assert created.status_code == 403
        assert post(client, url("users"), {"email": "n@example.com"}).status_code == 201


class TestList:
    def get(self, client, people, **params):
        as_user(client, people["admin"])
        return client.get(url("users"), params).json()

    def test_rows_show_who_they_are_what_they_hold_and_their_state(self, client, people):
        rows = {r["email"]: r for r in self.get(client, people)["results"]}
        ann = rows["ann@example.com"]
        assert ann["name"] == "Ann Ames" and ann["employee_id"] == "E1"
        assert ann["roles"] == ["learner"] and ann["is_active"] is True
        assert ann["locked"] is False and ann["must_change_password"] is True
        assert rows["adm@example.com"]["roles"] == ["admin"]

    def test_search_filter_and_order(self, client, people):
        assert [r["email"] for r in self.get(client, people, search="ames")["results"]] == [
            "ann@example.com"
        ]
        assert self.get(client, people, search="E1")["count"] == 1
        learners = self.get(client, people, role="learner")
        assert {r["email"] for r in learners["results"]} == {"ann@example.com", "bob@example.com"}
        emails = [r["email"] for r in self.get(client, people, ordering="-name")["results"]]
        assert emails == sorted(emails, reverse=True)

    def test_active_filter(self, client, people):
        User.objects.filter(pk=people["bob"].pk).update(is_active=False)
        inactive = self.get(client, people, active="false")
        assert [r["email"] for r in inactive["results"]] == ["bob@example.com"]
        assert self.get(client, people, active="true")["count"] == 5

    def test_locked_accounts_are_flagged_and_filterable(self, client, people):
        lock("bob")
        lock("ann", failures=2)  # not enough failures to lock
        lock("trn", ago=timedelta(hours=3))  # lock has expired
        body = self.get(client, people, locked="true")
        assert [r["email"] for r in body["results"]] == ["bob@example.com"]
        assert body["results"][0]["locked"] is True
        everyone = {r["email"]: r["locked"] for r in self.get(client, people)["results"]}
        assert everyone["bob@example.com"] is True and everyone["ann@example.com"] is False
        assert everyone["trn@example.com"] is False

    def test_paging(self, client, people):
        body = self.get(client, people, page_size=2, page=3)
        assert (body["count"], body["pages"], len(body["results"])) == (6, 3, 2)

    def test_query_count_stays_flat(self, client, people, django_assert_max_num_queries):
        as_user(client, people["admin"])
        with django_assert_max_num_queries(8):
            assert client.get(url("users"), {"page_size": 100}).status_code == 200


class TestDetail:
    def test_shows_profile_access_and_identities(self, client, people):
        from apps.accounts.models import UserIdentity

        UserIdentity.objects.create(
            user=people["ann"], provider="local", external_id="ann", email="ann@example.com"
        )
        as_user(client, people["admin"])
        body = client.get(url("user", people["ann"].pk)).json()
        assert body["first_name"] == "Ann" and body["timezone"] == "Asia/Kolkata"
        assert body["identities"] == [
            {"provider": "local", "external_id": "ann", "email": "ann@example.com"}
        ]
        assert body["is_staff"] is False and body["is_superuser"] is False
        assert body["can_edit_privileges"] is False and body["is_self"] is False
        assert body["date_joined"]

    def test_unknown_user_is_404(self, client, people):
        as_user(client, people["admin"])
        assert client.get(url("user", 99999)).status_code == 404


class TestCreate:
    def create(self, client, people, **data):
        as_user(client, people["admin"])
        return post(client, url("users"), data)

    def test_a_generated_password_is_returned_once_and_works(self, client, people):
        response = self.create(
            client, people, email="new@example.com", first_name="New", last_name="Hire"
        )
        assert response.status_code == 201
        body = response.json()
        assert body["roles"] == ["learner"] and body["must_change_password"] is True
        assert body["username"] == "new@example.com"
        temp = body["temporary_password"]
        assert User.objects.get(email="new@example.com").check_password(temp)
        # …and it is never written to the audit log.
        entry = AuditLog.objects.get(action="users.create")
        assert temp not in str(entry.changes) and entry.target_label == "new@example.com"
        assert entry.actor == people["admin"]
        fresh = client.get(url("user", body["id"])).json()
        assert "temporary_password" not in fresh

    def test_a_typed_password_is_used_and_not_echoed(self, client, people):
        body = self.create(
            client, people, email="typed@example.com", password="A-long-unusual-phrase-42"
        ).json()
        assert "temporary_password" not in body
        assert User.objects.get(email="typed@example.com").check_password(
            "A-long-unusual-phrase-42"
        )

    def test_a_weak_typed_password_is_refused(self, client, people):
        response = self.create(client, people, email="weak@example.com", password="12345678")
        assert response.status_code == 400 and response.json()["detail"]
        assert not User.objects.filter(email="weak@example.com").exists()

    def test_roles_and_extras(self, client, people):
        body = self.create(
            client,
            people,
            email="t@example.com",
            username="tee",
            employee_id="E77",
            timezone="Europe/London",
            roles=["trainer", "mentor"],
        ).json()
        assert body["roles"] == ["mentor", "trainer"] and body["username"] == "tee"
        assert body["employee_id"] == "E77" and body["timezone"] == "Europe/London"

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({"email": "ANN@example.com"}, "email"),
            ({"email": "x@example.com", "username": "ANN"}, "username"),
            ({"email": "x@example.com", "employee_id": "E1"}, "employee id"),
            ({"email": "x@example.com", "roles": ["wizard"]}, "wizard"),
        ],
    )
    def test_duplicates_and_unknowns_are_refused_in_plain_words(
        self, client, people, data, message
    ):
        response = self.create(client, people, **data)
        assert response.status_code == 400 and message in response.json()["detail"].lower()
        assert User.objects.count() == 6

    def test_an_invalid_email_is_refused(self, client, people):
        assert self.create(client, people, email="nope").status_code == 400
        assert self.create(client, people).status_code == 400


class TestUpdate:
    def patch(self, client, who, target, **data):
        as_user(client, who)
        return patch(client, url("user", target.pk), data)

    def test_edits_the_profile_and_logs_only_what_changed(self, client, people):
        response = self.patch(
            client,
            people["admin"],
            people["ann"],
            first_name="Anna",
            last_name="Ames",
            employee_id="E2",
            email="anna@example.com",
        )
        assert response.status_code == 200 and response.json()["name"] == "Anna Ames"
        entry = AuditLog.objects.get(action="users.update")
        assert entry.changes == {
            "first_name": {"before": "Ann", "after": "Anna"},
            "employee_id": {"before": "E1", "after": "E2"},
            "email": {"before": "ann@example.com", "after": "anna@example.com"},
        }

    def test_saving_without_changes_logs_nothing(self, client, people):
        self.patch(client, people["admin"], people["ann"], first_name="Ann")
        assert not AuditLog.objects.exists()

    def test_clearing_the_employee_id(self, client, people):
        self.patch(client, people["admin"], people["ann"], employee_id="")
        assert User.objects.get(pk=people["ann"].pk).employee_id is None

    def test_email_and_employee_id_must_stay_unique(self, client, people):
        taken = self.patch(client, people["admin"], people["ann"], email="BOB@example.com")
        assert taken.status_code == 400
        User.objects.filter(pk=people["bob"].pk).update(employee_id="E9")
        assert (
            self.patch(client, people["admin"], people["ann"], employee_id="E9").status_code == 400
        )

    def test_deactivate_and_reactivate_are_their_own_events(self, client, people):
        self.patch(client, people["admin"], people["bob"], is_active=False)
        assert User.objects.get(pk=people["bob"].pk).is_active is False
        self.patch(client, people["admin"], people["bob"], is_active=True)
        assert [e.action for e in AuditLog.objects.order_by("id")] == [
            "users.deactivate",
            "users.reactivate",
        ]

    def test_a_deactivated_person_can_no_longer_sign_in(self, client, people):
        User.objects.filter(pk=people["bob"].pk).update(is_active=False)
        client.logout()
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "bob@example.com", "password": "testpass123"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_you_cannot_deactivate_yourself(self, client, people):
        response = self.patch(client, people["admin"], people["admin"], is_active=False)
        assert response.status_code == 400 and "own account" in response.json()["detail"]

    def test_the_last_administrator_cannot_be_deactivated(self, client, people):
        User.objects.filter(pk=people["admin2"].pk).update(is_active=False)
        # Someone who may manage users (but is not an administrator) tries to
        # switch off the only administrator left.
        mentor_role = Role.objects.get(name=Role.Name.MENTOR)
        mentor_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="manage_users")
        )
        response = self.patch(client, people["mentor"], people["admin"], is_active=False)
        assert response.status_code == 400
        assert "nobody able to administer" in response.json()["detail"]
        assert User.objects.get(pk=people["admin"].pk).is_active is True

    def test_another_administrator_can_be_deactivated_while_one_remains(self, client, people):
        response = self.patch(client, people["admin"], people["admin2"], is_active=False)
        assert response.status_code == 200

    def test_privilege_flags_are_for_superusers_only(self, client, people):
        response = self.patch(client, people["admin"], people["ann"], is_staff=True)
        assert response.status_code == 403
        assert User.objects.get(pk=people["ann"].pk).is_staff is False

    def test_a_superuser_can_grant_and_revoke_but_not_strip_themselves(self, client, people):
        root = User.objects.create_superuser("root", "root@example.com", "x")
        assert self.patch(client, root, people["ann"], is_staff=True).status_code == 200
        assert User.objects.get(pk=people["ann"].pk).is_staff is True
        assert self.patch(client, root, root, is_superuser=False).status_code == 400

    def test_force_a_password_change(self, client, people):
        User.objects.filter(pk=people["ann"].pk).update(must_change_password=False)
        self.patch(client, people["admin"], people["ann"], must_change_password=True)
        assert User.objects.get(pk=people["ann"].pk).must_change_password is True


class TestPassword:
    def reset(self, client, people, target="ann", **data):
        as_user(client, people["admin"])
        return post(client, url("set-password", people[target].pk), data)

    def test_generates_one_and_forces_a_change(self, client, people):
        body = self.reset(client, people).json()
        ann = User.objects.get(pk=people["ann"].pk)
        assert ann.check_password(body["temporary_password"]) and ann.must_change_password is True
        assert not ann.check_password("testpass123")
        entry = AuditLog.objects.get(action="users.set_password")
        assert entry.changes == {"generated": True, "must_change_password": True}
        assert body["temporary_password"] not in str(entry.changes)

    def test_a_typed_password_is_checked_and_not_echoed(self, client, people):
        body = self.reset(client, people, password="Another-long-phrase-77").json()
        assert body == {"ok": True}
        assert User.objects.get(pk=people["ann"].pk).check_password("Another-long-phrase-77")
        assert self.reset(client, people, password="short").status_code == 400

    def test_it_signs_the_person_out_everywhere(self, client, people):
        ann = Client_for(people["ann"])
        assert ann.get(reverse("accounts_api:session")).json()["authenticated"] is True
        self.reset(client, people)
        assert ann.get(reverse("accounts_api:session")).json()["authenticated"] is False


def Client_for(user):
    from django.test import Client

    c = Client()
    c.force_login(user)
    return c


class TestUnlock:
    def test_clears_the_lock_and_logs_it(self, client, people):
        lock("bob")
        lock("bob")
        as_user(client, people["admin"])
        response = post(client, url("unlock", people["bob"].pk))
        assert response.json() == {"cleared": 2}
        assert not AccessAttempt.objects.filter(username="bob").exists()
        assert client.get(url("users"), {"locked": "true"}).json()["count"] == 0
        assert AuditLog.objects.get(action="users.unlock").changes == {"failed_attempts_cleared": 2}

    def test_unlocking_someone_who_is_not_locked_is_harmless(self, client, people):
        as_user(client, people["admin"])
        assert post(client, url("unlock", people["bob"].pk)).json() == {"cleared": 0}


class TestRoles:
    def set(self, client, who, target, roles):
        as_user(client, who)
        return put(client, url("user-roles", target.pk), {"roles": roles})

    def test_replaces_the_roles_and_logs_before_and_after(self, client, people):
        response = self.set(client, people["admin"], people["ann"], ["learner", "mentor"])
        assert response.json() == {"roles": ["learner", "mentor"]}
        entry = AuditLog.objects.get(action="users.set_roles")
        assert entry.changes == {"before": ["learner"], "after": ["learner", "mentor"]}

    def test_the_new_role_takes_effect_immediately(self, client, people):
        self.set(client, people["admin"], people["ann"], ["trainer"])
        client.force_login(people["ann"])
        body = client.get(reverse("accounts_api:session")).json()["user"]
        assert "catalog.author_content" in body["capabilities"] and body["roles"] == ["trainer"]

    def test_no_change_logs_nothing(self, client, people):
        self.set(client, people["admin"], people["ann"], ["learner"])
        assert not AuditLog.objects.exists()

    def test_unknown_role_is_refused(self, client, people):
        response = self.set(client, people["admin"], people["ann"], ["wizard"])
        assert response.status_code == 400 and "wizard" in response.json()["detail"]

    def test_you_cannot_remove_your_own_admin_role(self, client, people):
        response = self.set(client, people["admin"], people["admin"], ["learner"])
        assert response.status_code == 400 and "own Admin role" in response.json()["detail"]

    def test_another_admin_can_be_demoted_while_one_remains(self, client, people):
        assert self.set(client, people["admin"], people["admin2"], ["trainer"]).status_code == 200

    def test_the_last_admin_cannot_be_demoted(self, client, people):
        # Only `adm2` (an Admin) acts; `adm` is demoted first, leaving adm2 alone.
        self.set(client, people["admin2"], people["admin"], ["trainer"])
        # A second actor with role-management rights tries to demote the last one.
        mentor_role = Role.objects.get(name=Role.Name.MENTOR)
        mentor_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="manage_roles")
        )
        response = self.set(client, people["mentor"], people["admin2"], ["learner"])
        assert response.status_code == 400
        assert "nobody able to administer" in response.json()["detail"]
