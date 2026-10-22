import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit import services as audit

pytestmark = pytest.mark.django_db


@pytest.fixture
def entries(rf, make_role_user):
    actor = make_role_user(Role.Name.ADMIN, username="adm", email="adm@example.com")
    request = rf.post("/", REMOTE_ADDR="10.0.0.9")
    request.user = actor
    audit.record(request, "results.export", target_type="course", target_id=1, target_label="Alpha")
    audit.record(
        request,
        "results.reset_attempts",
        target_type="activity",
        target_id=5,
        target_label="bob@example.com · Quiz",
        changes={"attempts_deleted": 2},
    )
    return actor


def get(client, path="console_api:audit", **params):
    return client.get(reverse(path), params)


def test_only_those_who_may_view_the_audit_log_can(client, make_role_user, entries):
    assert get(client).status_code == 403
    for role in (Role.Name.LEARNER, Role.Name.MENTOR, Role.Name.TRAINER):
        client.force_login(make_role_user(role, username=role, email=f"{role}@example.com"))
        assert get(client).status_code == 403, role
        assert get(client, "console_api:audit-actions").status_code == 403, role
    client.force_login(entries)
    assert get(client).status_code == 200


def test_newest_first_with_actor_target_and_changes(client, entries):
    client.force_login(entries)
    body = get(client).json()
    assert [e["action"] for e in body["results"]] == ["results.reset_attempts", "results.export"]
    first = body["results"][0]
    assert first["actor"] == "adm@example.com"
    assert first["target"] == "bob@example.com · Quiz"
    assert first["changes"] == {"attempts_deleted": 2}
    assert first["ip_address"] == "10.0.0.9" and first["created_at"]
    assert body["count"] == 2


def test_filter_by_action_and_search(client, entries):
    client.force_login(entries)
    assert get(client, action="results.export").json()["count"] == 1
    assert get(client, search="bob").json()["count"] == 1
    assert get(client, search="adm@example.com").json()["count"] == 2
    assert get(client, search="zzz").json()["count"] == 0


def test_the_action_filter_lists_what_has_been_logged(client, entries):
    client.force_login(entries)
    assert get(client, "console_api:audit-actions").json()["results"] == [
        "results.export",
        "results.reset_attempts",
    ]


def test_paging(client, entries):
    client.force_login(entries)
    body = get(client, page_size=1, page=2).json()
    assert body["pages"] == 2 and [e["action"] for e in body["results"]] == ["results.export"]
