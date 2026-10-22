import pytest
from django.contrib import admin as dj_admin
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.accounts.rbac import KNOWN_ACTIONS, capabilities_for
from apps.catalog import services
from apps.catalog.admin import ContentNodeAdmin
from apps.catalog.models import ContentNode, CourseVersion

pytestmark = pytest.mark.django_db


class TestCapabilities:
    def test_learner_has_none(self, make_role_user):
        assert capabilities_for(make_role_user(Role.Name.LEARNER)) == []

    def test_trainer_can_author_but_not_publish(self, make_role_user):
        caps = capabilities_for(make_role_user(Role.Name.TRAINER))
        # Authoring plus seeing (and resetting) learners' quiz results.
        assert caps == [
            "catalog.author_content",
            "progress.view_results",
            "progress.manage_attempts",
        ]
        assert "catalog.publish_courseversion" not in caps

    def test_admin_role_can_publish(self, make_role_user):
        caps = capabilities_for(make_role_user(Role.Name.ADMIN))
        assert "catalog.author_content" in caps
        assert "catalog.publish_courseversion" in caps

    def test_superuser_gets_every_known_action(self, django_user_model):
        root = django_user_model.objects.create_superuser("root", "root@example.com", "x")
        assert capabilities_for(root) == list(KNOWN_ACTIONS)

    def test_session_endpoint_reports_capabilities(self, client, make_role_user):
        client.force_login(make_role_user(Role.Name.TRAINER))
        body = client.get(reverse("accounts_api:session")).json()
        assert "catalog.author_content" in body["user"]["capabilities"]
        assert "catalog.publish_courseversion" not in body["user"]["capabilities"]
        assert body["user"]["roles"] == ["trainer"]


class TestAdminLocksNonDraftVersions:
    @pytest.fixture
    def published_node(self, make_role_user):
        user = make_role_user(Role.Name.TRAINER)
        course = services.create_course(title="Locked course", user=user)
        version = services.open_version(course)
        module = services.add_node(version.root_node, title="Module")
        CourseVersion.objects.filter(pk=version.pk).update(state=CourseVersion.State.PUBLISHED)
        return ContentNode.objects.get(pk=module.pk)

    def test_trainer_cannot_change_or_delete_a_published_node(self, published_node, rf):
        request = rf.get("/")
        request.user = User.objects.get(username="trainer_user")
        model_admin = ContentNodeAdmin(ContentNode, dj_admin.site)
        assert model_admin.has_change_permission(request, published_node) is False
        assert model_admin.has_delete_permission(request, published_node) is False

    def test_superuser_keeps_emergency_access(self, django_user_model, published_node, rf):
        root = django_user_model.objects.create_superuser("root", "root@example.com", "x")
        request = rf.get("/")
        request.user = root
        model_admin = ContentNodeAdmin(ContentNode, dj_admin.site)
        assert model_admin.has_change_permission(request, published_node) is True
