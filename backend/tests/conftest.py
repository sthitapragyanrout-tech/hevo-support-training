import pytest
from django.contrib.auth.models import Permission

from apps.accounts.models import Role, RoleAssignment, User
from apps.accounts.rbac import ROLE_PERMISSIONS


@pytest.fixture
def make_role_user(db):
    """Factory fixture: make_role_user("trainer") -> a User holding that
    role, with its ROLE_PERMISSIONS attached directly to the Role, mirroring
    what the `seed_roles` management command does in real environments.
    """

    def _make(role_name: str, **user_kwargs) -> User:
        role, _ = Role.objects.get_or_create(name=role_name)

        perms = []
        for codename in ROLE_PERMISSIONS.get(role_name, []):
            app_label, codename_only = codename.split(".", 1)
            perms.append(
                Permission.objects.get(content_type__app_label=app_label, codename=codename_only)
            )
        role.permissions.set(perms)

        defaults = {
            "username": f"{role_name}_user",
            "email": f"{role_name}@example.com",
        }
        defaults.update(user_kwargs)
        user = User.objects.create_user(password="testpass123", **defaults)
        RoleAssignment.objects.create(user=user, role=role)
        return user

    return _make
