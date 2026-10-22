"""Admin Console → Sign-in activity (django-axes' logs), read-only."""

from datetime import timedelta

import pytest
from axes.models import AccessFailureLog, AccessLog
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role

pytestmark = pytest.mark.django_db


def url():
    return reverse("console_api:signins")


@pytest.fixture
def people(make_role_user):
    return {
        "admin": make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="trn", email="trn@example.com"),
        "ann": make_role_user(
            Role.Name.LEARNER,
            username="ann",
            email="ann@example.com",
            first_name="Ann",
            last_name="Ames",
        ),
    }


def stamp(model, when, **fields):
    """Create a log row and back-date it (the time is stamped on creation)."""
    row = model.objects.create(**fields)
    model.objects.filter(pk=row.pk).update(attempt_time=when)
    return row


@pytest.fixture
def logs():
    now = timezone.now()
    stamp(
        AccessLog,
        now - timedelta(hours=1),
        username="ann",
        ip_address="10.0.0.1",
        user_agent="Chrome",
        path_info="/api/v1/auth/login/",
    )
    stamp(
        AccessLog,
        now - timedelta(days=3),
        username="ghost",
        ip_address="10.0.0.2",
        user_agent="Firefox",
        path_info="/api/v1/auth/login/",
    )
    stamp(
        AccessFailureLog,
        now - timedelta(minutes=5),
        username="ann",
        ip_address="10.0.0.9",
        user_agent="curl",
        path_info="/api/v1/auth/login/",
        locked_out=True,
    )
    stamp(
        AccessFailureLog,
        now - timedelta(days=2),
        username="nobody",
        ip_address="10.0.0.8",
        user_agent="curl",
        path_info="/api/v1/auth/login/",
        locked_out=False,
    )
    return now


def get(client, who, **params):
    client.force_login(who)
    return client.get(url(), params)


def test_only_those_who_manage_users_may_look(client, people, logs):
    assert client.get(url()).status_code == 403
    for who in ("trainer", "ann"):
        assert get(client, people[who]).status_code == 403, who
    assert get(client, people["admin"]).status_code == 200


def test_successful_sign_ins_newest_first_with_who_and_where(client, people, logs):
    body = get(client, people["admin"]).json()
    assert body["kind"] == "success" and body["count"] == 2
    first, second = body["results"]
    assert (first["username"], first["ip_address"], first["user_agent"]) == (
        "ann",
        "10.0.0.1",
        "Chrome",
    )
    assert first["name"] == "Ann Ames" and first["user_id"] == people["ann"].pk
    assert first["signed_out_at"] is None and first["when"]
    # A username that no longer exists is still shown, just not linked.
    assert second["username"] == "ghost" and second["user_id"] is None and second["name"] is None


def test_failed_attempts_say_whether_they_locked_the_account(client, people, logs):
    body = get(client, people["admin"], kind="failed").json()
    assert body["kind"] == "failed"
    assert [(r["username"], r["locked_out"]) for r in body["results"]] == [
        ("ann", True),
        ("nobody", False),
    ]
    assert "signed_out_at" not in body["results"][0]


def test_the_locked_out_filter_applies_to_failures(client, people, logs):
    body = get(client, people["admin"], kind="failed", locked="true").json()
    assert [r["username"] for r in body["results"]] == ["ann"]


def test_search_by_username_address_or_browser(client, people, logs):
    assert get(client, people["admin"], search="ghost").json()["count"] == 1
    assert get(client, people["admin"], search="10.0.0.1").json()["count"] == 1
    assert get(client, people["admin"], search="firefox").json()["count"] == 1
    assert get(client, people["admin"], kind="failed", search="curl").json()["count"] == 2
    assert get(client, people["admin"], search="nothing").json()["count"] == 0


def test_date_range(client, people, logs):
    today = timezone.localdate()
    assert get(client, people["admin"], **{"from": today.isoformat()}).json()["count"] == 1
    old = (today - timedelta(days=5)).isoformat()
    recent_to = (today - timedelta(days=2)).isoformat()
    assert get(client, people["admin"], **{"from": old, "to": recent_to}).json()["count"] == 1
    assert get(client, people["admin"], **{"to": old}).json()["count"] == 0


def test_a_bad_date_is_ignored_not_an_error(client, people, logs):
    assert get(client, people["admin"], **{"from": "garbage"}).json()["count"] == 2


def test_paging(client, people, logs):
    body = get(client, people["admin"], page_size=1, page=2).json()
    assert (body["count"], body["pages"], body["results"][0]["username"]) == (2, 2, "ghost")


def test_a_sign_out_is_shown(client, people):
    row = AccessLog.objects.create(username="ann", ip_address="10.0.0.1", user_agent="x")
    AccessLog.objects.filter(pk=row.pk).update(logout_time=timezone.now())
    assert get(client, people["admin"]).json()["results"][0]["signed_out_at"]


def test_query_count_is_flat(client, people, logs, django_assert_max_num_queries):
    for i in range(20):
        AccessLog.objects.create(username="ann", ip_address=f"10.1.0.{i}", user_agent="x")
    client.force_login(people["admin"])
    with django_assert_max_num_queries(8):
        assert client.get(url(), {"page_size": 100}).status_code == 200


def test_failed_sign_ins_are_actually_recorded(settings):
    """django-axes keeps no failure log unless asked to; the screen above would
    otherwise be permanently empty."""
    assert settings.AXES_ENABLE_ACCESS_FAILURE_LOG is True
