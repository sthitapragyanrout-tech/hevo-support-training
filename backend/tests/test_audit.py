import pytest

from apps.audit import services as audit
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


class TestRecord:
    def test_the_actor_ip_and_target_are_captured(self, rf, django_user_model):
        user = django_user_model.objects.create_user("a", "a@example.com", "x")
        request = rf.post("/", REMOTE_ADDR="10.1.2.3")
        request.user = user
        audit.record(
            request,
            "demo.thing",
            target_type="thing",
            target_id=7,
            target_label="Thing seven",
            changes={"before": 1, "after": 2},
        )
        entry = AuditLog.objects.get()
        assert (entry.actor, entry.actor_label) == (user, "a@example.com")
        assert entry.action == "demo.thing" and entry.target_id == "7"
        assert entry.target_label == "Thing seven"
        assert entry.changes == {"before": 1, "after": 2}
        assert entry.ip_address == "10.1.2.3"

    def test_secrets_never_reach_the_log(self, rf, django_user_model):
        user = django_user_model.objects.create_user("a", "a@example.com", "x")
        request = rf.post("/")
        request.user = user
        audit.record(
            request,
            "users.create",
            changes={
                "email": "x@example.com",
                "password": "hunter2",
                "must_change_password": True,
                "temporary_password": "abc",
                "nested": {"api_token": "t", "ok": "fine"},
                "list": [{"secret": "s"}],
            },
        )
        stored = AuditLog.objects.get().changes
        assert stored["email"] == "x@example.com"
        assert stored["password"] == "[hidden]"
        assert stored["must_change_password"] is True  # a flag about a password, not one
        assert stored["temporary_password"] == "[hidden]"
        assert stored["nested"] == {"api_token": "[hidden]", "ok": "fine"}
        assert stored["list"] == [{"secret": "[hidden]"}]

    def test_the_actor_label_survives_the_account_being_removed(self, rf, django_user_model):
        user = django_user_model.objects.create_user("gone", "gone@example.com", "x")
        request = rf.post("/")
        request.user = user
        audit.record(request, "demo.thing")
        user.delete()
        entry = AuditLog.objects.get()
        assert entry.actor is None and entry.actor_label == "gone@example.com"

    def test_a_system_entry_has_no_actor(self):
        audit.record(None, "system.job")
        assert AuditLog.objects.get().actor_label == "system"

    def test_the_log_is_read_only_in_the_emergency_admin(self, admin_client):
        from django.urls import reverse

        audit.record(None, "system.job")
        assert admin_client.get(reverse("admin:audit_auditlog_changelist")).status_code == 200
        assert admin_client.get(reverse("admin:audit_auditlog_add")).status_code == 403
