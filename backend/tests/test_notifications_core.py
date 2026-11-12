"""Notifications: raising one (idempotently, safely), resolving and clearing them, and the API that
serves a person's own list. Who gets told about what is in `test_notifications_events.py`."""

import logging
from datetime import timedelta

import pytest
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.notifications import services
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(make_role_user):
    return {
        "ann": make_role_user(Role.Name.LEARNER, username="ann", email="ann@e.com"),
        "bob": make_role_user(Role.Name.LEARNER, username="bob", email="bob@e.com"),
    }


class TestRaisingOne:
    def test_it_writes_a_plain_message_for_the_person(self, people):
        made = services.notify(
            people["ann"], "enrolled", "You’re enrolled", "On Course", "/courses/1"
        )
        assert made is not None
        assert (made.user, made.kind, made.title, made.body, made.link) == (
            people["ann"],
            "enrolled",
            "You’re enrolled",
            "On Course",
            "/courses/1",
        )
        assert made.read_at is None and made.is_read is False

    def test_long_text_is_cut_to_fit(self, people):
        made = services.notify(people["ann"], "k", "t" * 500, "b" * 5000)
        assert len(made.title) == services.MAX_TITLE and len(made.body) == services.MAX_BODY

    @pytest.mark.parametrize(
        "link,kept",
        [
            ("/courses/1", "/courses/1"),
            ("/admin/ratings/quiz/3", "/admin/ratings/quiz/3"),
            ("https://evil.example/x", ""),
            ("//evil.example/x", ""),
            ("javascript:alert(1)", ""),
            ("courses/1", ""),
            ("", ""),
        ],
    )
    def test_a_link_can_only_point_inside_the_app(self, people, link, kept):
        assert services.notify(people["ann"], "k", "t", link=link).link == kept

    def test_nobody_is_told_who_is_missing_or_deactivated(self, people):
        assert services.notify(None, "k", "t") is None
        people["bob"].is_active = False
        people["bob"].save()
        assert services.notify(people["bob"], "k", "t") is None
        assert Notification.objects.count() == 0


class TestOnlyOnce:
    def test_the_same_key_for_the_same_person_is_raised_once(self, people):
        first = services.notify(people["ann"], "k", "t", dedupe_key="due:1:x")
        second = services.notify(people["ann"], "k", "t again", dedupe_key="due:1:x")
        assert first is not None and second is None
        assert list(Notification.objects.values_list("title", flat=True)) == ["t"]

    def test_a_different_key_or_a_different_person_is_a_new_message(self, people):
        services.notify(people["ann"], "k", "a", dedupe_key="due:1:x")
        assert services.notify(people["ann"], "k", "b", dedupe_key="due:1:y") is not None
        assert services.notify(people["bob"], "k", "c", dedupe_key="due:1:x") is not None
        assert Notification.objects.count() == 3

    def test_no_key_never_dedupes(self, people):
        services.notify(people["ann"], "k", "same")
        services.notify(people["ann"], "k", "same")
        assert Notification.objects.count() == 2

    def test_many_people_each_get_their_own_copy_with_their_own_key(self, people):
        people["bob"].is_active = False
        people["bob"].save()
        made = services.notify_many(
            [people["ann"], people["bob"]], "k", "t", dedupe_key="waiting:sim:7"
        )
        assert [n.user for n in made] == [people["ann"]]
        assert Notification.objects.get().dedupe_key == f"waiting:sim:7:{people['ann'].pk}"
        assert services.notify_many([people["ann"]], "k", "t", dedupe_key="waiting:sim:7") == []


class TestItNeverBreaksTheCaller:
    def test_a_failure_is_swallowed_logged_and_leaves_the_transaction_usable(
        self, people, monkeypatch, caplog
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("database says no")

        monkeypatch.setattr(Notification.objects, "create", boom)
        with caplog.at_level(logging.ERROR):
            with transaction.atomic():
                assert services.notify(people["ann"], "k", "t") is None
                # The surrounding transaction is still healthy: later work in it succeeds.
                people["ann"].first_name = "Still"
                people["ann"].save()
        assert "Could not write a 'k' notification" in caplog.text
        people["ann"].refresh_from_db()
        assert people["ann"].first_name == "Still"

    def test_the_message_rolls_back_with_the_event_that_raised_it(self, people):
        with pytest.raises(ValueError):
            with transaction.atomic():
                services.notify(people["ann"], "k", "t")
                raise ValueError("the event failed")
        assert Notification.objects.count() == 0


class TestResolving:
    def test_it_clears_unread_notices_for_a_prefix_and_nothing_else(self, people):
        services.notify(people["ann"], "k", "a", dedupe_key="waiting:sim:7:1")
        services.notify(people["bob"], "k", "b", dedupe_key="waiting:sim:7:2")
        services.notify(people["ann"], "k", "other work", dedupe_key="waiting:sim:70:1")
        services.notify(people["ann"], "k", "unkeyed")
        assert services.resolve("waiting:sim:7:") == 2
        unread = set(
            Notification.objects.filter(read_at__isnull=True).values_list("title", flat=True)
        )
        assert unread == {"other work", "unkeyed"}
        assert services.resolve("waiting:sim:7:") == 0  # nothing left to clear

    def test_an_empty_prefix_clears_nothing(self, people):
        services.notify(people["ann"], "k", "a", dedupe_key="x")
        assert services.resolve("") == 0
        assert Notification.objects.filter(read_at__isnull=True).count() == 1


class TestReading:
    def test_marking_one_read_keeps_the_first_time(self, people):
        made = services.notify(people["ann"], "k", "t")
        first = timezone.now() - timedelta(hours=1)
        services.mark_read(people["ann"], made.pk, now=first)
        services.mark_read(people["ann"], made.pk)
        made.refresh_from_db()
        assert made.read_at == first

    def test_nobody_can_read_someone_elses(self, people):
        made = services.notify(people["ann"], "k", "t")
        assert services.mark_read(people["bob"], made.pk) is None
        made.refresh_from_db()
        assert made.read_at is None

    def test_mark_all_only_touches_the_callers(self, people):
        services.notify(people["ann"], "k", "a")
        services.notify(people["ann"], "k", "b")
        services.notify(people["bob"], "k", "c")
        assert services.mark_all_read(people["ann"]) == 2
        assert services.unread_count(people["ann"]) == 0
        assert services.unread_count(people["bob"]) == 1


class TestPruning:
    def make(self, user, title, *, age_days, read):
        n = services.notify(user, "k", title)
        Notification.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=age_days),
            read_at=timezone.now() if read else None,
        )

    def test_old_read_notices_go_and_recent_or_unread_ones_stay(self, people):
        ann = people["ann"]
        self.make(ann, "old read", age_days=91, read=True)
        self.make(ann, "recent read", age_days=89, read=True)
        self.make(ann, "old unread", age_days=120, read=False)
        self.make(ann, "very old unread", age_days=181, read=False)
        assert services.prune() == 2
        assert set(Notification.objects.values_list("title", flat=True)) == {
            "recent read",
            "old unread",
        }

    def test_it_is_safe_to_run_again(self, people):
        self.make(people["ann"], "old read", age_days=200, read=True)
        assert services.prune() == 1 and services.prune() == 0


class TestTheApi:
    def get(self, client, user, name="list", *args, query=""):
        client.force_login(user)
        return client.get(reverse(f"notifications_api:{name}", args=args) + query)

    def post(self, client, user, name, *args):
        client.force_login(user)
        return client.post(reverse(f"notifications_api:{name}", args=args))

    def test_every_endpoint_needs_a_signed_in_person(self, client):
        assert client.get(reverse("notifications_api:list")).status_code in (401, 403)
        assert client.get(reverse("notifications_api:unread-count")).status_code in (401, 403)
        assert client.post(reverse("notifications_api:read-all")).status_code in (401, 403)
        assert client.post(reverse("notifications_api:read", args=[1])).status_code in (401, 403)

    def test_the_list_is_the_callers_own_newest_first_with_the_unread_count(self, client, people):
        services.notify(people["ann"], "a", "older")
        newest = services.notify(people["ann"], "b", "newer", link="/courses/1")
        services.notify(people["bob"], "c", "not yours")
        body = self.get(client, people["ann"]).json()
        assert [r["title"] for r in body["results"]] == ["newer", "older"]
        assert body["unread_count"] == 2 and body["count"] == 2
        first = body["results"][0]
        assert first == {
            "id": newest.pk,
            "kind": "b",
            "title": "newer",
            "body": "",
            "link": "/courses/1",
            "created_at": first["created_at"],
            "read": False,
        }
        assert "dedupe_key" not in first and "user" not in first

    def test_unread_only_and_pagination(self, client, people):
        for i in range(5):
            services.notify(people["ann"], "k", f"n{i}")
        services.mark_read(people["ann"], Notification.objects.order_by("id").first().pk)
        unread = self.get(client, people["ann"], query="?unread=1").json()
        assert unread["count"] == 4 and unread["unread_count"] == 4
        page = self.get(client, people["ann"], query="?page_size=2&page=3").json()
        assert [r["title"] for r in page["results"]] == ["n0"]
        assert (page["page"], page["pages"], page["count"]) == (3, 3, 5)

    @pytest.mark.parametrize(
        "query", ["?page=999", "?page=-4", "?page=x", "?page_size=0", "?page_size=999"]
    )
    def test_odd_paging_is_clamped_not_an_error(self, client, people, query):
        services.notify(people["ann"], "k", "t")
        response = self.get(client, people["ann"], query=query)
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1

    def test_the_bell_count(self, client, people):
        services.notify(people["ann"], "k", "a")
        services.notify(people["bob"], "k", "b")
        assert self.get(client, people["ann"], "unread-count").json() == {"unread_count": 1}

    def test_reading_one_marks_it_and_returns_the_new_count(self, client, people):
        made = services.notify(people["ann"], "k", "a")
        services.notify(people["ann"], "k", "b")
        body = self.post(client, people["ann"], "read", made.pk).json()
        assert body["read"] is True and body["unread_count"] == 1

    def test_someone_elses_notification_is_not_found_and_stays_unread(self, client, people):
        made = services.notify(people["ann"], "k", "a")
        assert self.post(client, people["bob"], "read", made.pk).status_code == 404
        assert self.post(client, people["bob"], "read", 999999).status_code == 404
        made.refresh_from_db()
        assert made.read_at is None

    def test_read_all_touches_only_the_callers(self, client, people):
        services.notify(people["ann"], "k", "a")
        services.notify(people["bob"], "k", "b")
        assert self.post(client, people["ann"], "read-all").json() == {"unread_count": 0}
        assert services.unread_count(people["bob"]) == 1
