"""A signed-in person changing their own password."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

OLD = "testpass123"
NEW = "A-brand-new-phrase-91"


@pytest.fixture
def ann(make_role_user):
    user = make_role_user(Role.Name.LEARNER, username="ann", email="ann@example.com")
    assert user.must_change_password is True  # new accounts must change it
    return user


def change(client, current=OLD, new=NEW):
    return client.post(
        reverse("accounts_api:password"),
        {"current_password": current, "new_password": new},
        content_type="application/json",
    )


def test_changing_it_works_clears_the_flag_and_keeps_you_signed_in(client, ann):
    client.force_login(ann)
    response = change(client)
    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is False
    ann.refresh_from_db()
    assert ann.check_password(NEW) and not ann.check_password(OLD)
    assert ann.must_change_password is False
    assert client.get(reverse("accounts_api:session")).json()["authenticated"] is True


def test_the_new_password_is_what_signs_you_in_afterwards(client, ann):
    client.force_login(ann)
    change(client)
    fresh = Client()
    ok = fresh.post(
        reverse("accounts_api:login"),
        {"login": "ann@example.com", "password": NEW},
        content_type="application/json",
    )
    bad = Client().post(
        reverse("accounts_api:login"),
        {"login": "ann@example.com", "password": OLD},
        content_type="application/json",
    )
    assert ok.status_code == 200 and bad.status_code == 400


def test_other_sessions_end(client, ann):
    other = Client()
    other.force_login(ann)
    client.force_login(ann)
    change(client)
    assert other.get(reverse("accounts_api:session")).json()["authenticated"] is False
    assert client.get(reverse("accounts_api:session")).json()["authenticated"] is True


def test_the_wrong_current_password_is_refused_and_nothing_changes(client, ann):
    client.force_login(ann)
    response = change(client, current="not-it")
    assert response.status_code == 400 and "current password" in response.json()["detail"]
    ann.refresh_from_db()
    assert ann.check_password(OLD) and ann.must_change_password is True
    assert not AuditLog.objects.exists()


def test_it_must_be_different(client, ann):
    client.force_login(ann)
    response = change(client, new=OLD)
    assert response.status_code == 400 and "different" in response.json()["detail"]


@pytest.mark.parametrize("weak", ["short1", "12345678901234", "password"])
def test_weak_passwords_are_refused_in_plain_words(client, ann, weak):
    client.force_login(ann)
    response = change(client, new=weak)
    assert response.status_code == 400 and response.json()["detail"]
    ann.refresh_from_db()
    assert ann.check_password(OLD)


def test_a_password_like_your_email_is_refused(client, ann):
    client.force_login(ann)
    assert change(client, new="ann@example.com").status_code == 400


def test_missing_fields_are_a_400(client, ann):
    client.force_login(ann)
    response = client.post(
        reverse("accounts_api:password"), {"current_password": OLD}, content_type="application/json"
    )
    assert response.status_code == 400


def test_you_must_be_signed_in(client, ann):
    assert change(client).status_code == 403
    ann.refresh_from_db()
    assert ann.check_password(OLD)


def test_the_change_is_logged_without_the_password(client, ann):
    client.force_login(ann)
    change(client)
    entry = AuditLog.objects.get(action="account.change_password")
    assert entry.actor == ann and entry.target_label == "ann@example.com"
    assert NEW not in str(entry.changes) and OLD not in str(entry.changes)


class TestEnforcementSwitch:
    """New and reset accounts are *flagged*, but nobody is forced to change a
    password unless `ENFORCE_PASSWORD_CHANGE` is on."""

    def session_user(self, client, user):
        client.force_login(user)
        return client.get(reverse("accounts_api:session")).json()["user"]

    def test_it_is_off_by_default(self, client, ann, settings):
        assert settings.ENFORCE_PASSWORD_CHANGE is False
        body = self.session_user(client, ann)
        assert body["must_change_password"] is True  # still recorded
        assert body["password_change_required"] is False  # but nothing forces it

    def test_switched_on_it_is_required_for_a_flagged_account(self, client, ann, settings):
        settings.ENFORCE_PASSWORD_CHANGE = True
        assert self.session_user(client, ann)["password_change_required"] is True

    def test_switched_on_it_is_not_required_once_changed(self, client, ann, settings):
        settings.ENFORCE_PASSWORD_CHANGE = True
        ann.must_change_password = False
        ann.save()
        assert self.session_user(client, ann)["password_change_required"] is False

    def test_the_voluntary_screen_works_either_way(self, client, ann, settings):
        client.force_login(ann)
        assert change(client).status_code == 200
