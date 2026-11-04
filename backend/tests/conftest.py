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


@pytest.fixture
def media_dirs(tmp_path, settings):
    """A private media folder and broker folder for one test."""
    root = tmp_path / "media"
    broker = tmp_path / "broker"
    for sub in ("queue", "control", "processed"):
        (broker / sub).mkdir(parents=True)
    settings.MEDIA_ROOT = str(root)
    settings.CELERY_BROKER_FOLDER = str(broker)
    return root


@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """One 2-second clip shared by the whole run (ffmpeg only runs once)."""
    from tests.media_helpers import HAVE_FFMPEG, make_clip

    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe are not installed")
    return make_clip(tmp_path_factory.mktemp("clips") / "sample.mp4")
