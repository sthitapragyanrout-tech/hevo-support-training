import pytest
from django.contrib.auth.models import AnonymousUser

from apps.accounts.rbac import ROLE_PERMISSIONS, can

pytestmark = pytest.mark.django_db

# The M1-relevant subset of the §11 seed matrix.
ACTIONS = [
    "catalog.author_content",
    "catalog.publish_courseversion",
    "accounts.manage_users",
    "accounts.manage_roles",
]


class TestCanTruthTable:
    @pytest.mark.parametrize("role_name", list(ROLE_PERMISSIONS.keys()))
    @pytest.mark.parametrize("action", ACTIONS)
    def test_matches_role_permissions_matrix(self, make_role_user, role_name, action):
        user = make_role_user(role_name)
        expected = action in ROLE_PERMISSIONS[role_name]
        assert can(user, action) is expected

    def test_superuser_always_true(self, django_user_model):
        superuser = django_user_model.objects.create_superuser(
            username="super", email="super@example.com", password="x"
        )
        for action in ACTIONS:
            assert can(superuser, action) is True

    def test_unauthenticated_always_false(self):
        for action in ACTIONS:
            assert can(AnonymousUser(), action) is False

    def test_scope_check_is_currently_a_noop(self, make_role_user):
        """M1 has nothing to scope against (no Program/Cohort exist yet) —
        once a user passes the global permission check, an object-scoped
        call currently always succeeds too. This test exists so the M2
        follow-up (real scope checking in accounts/rbac.py::_scope_check)
        isn't silently forgotten — see the docstring there.
        """
        admin = make_role_user("admin")
        assert can(admin, "catalog.author_content", obj=object()) is True
