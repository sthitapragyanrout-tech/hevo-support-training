"""Django Admin is restricted emergency access now: superusers only, under
/django-admin/, and removable with one setting once the console has parity."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role

pytestmark = pytest.mark.django_db


def test_it_lives_under_django_admin_so_the_spa_can_own_admin():
    assert reverse("admin:index") == "/django-admin/"


def test_a_superuser_gets_in(admin_client):
    assert admin_client.get(reverse("admin:index")).status_code == 200


def test_the_header_says_it_is_for_emergencies(admin_client):
    assert "Emergency back-office" in admin_client.get(reverse("admin:index")).content.decode()


@pytest.mark.parametrize("role", [Role.Name.ADMIN, Role.Name.TRAINER, Role.Name.LEARNER])
def test_staff_with_a_role_but_no_superuser_flag_are_turned_away(client, make_role_user, role):
    user = make_role_user(role)
    user.is_staff = True  # used to be enough
    user.save()
    client.force_login(user)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302 and "login" in response["Location"]


def test_an_inactive_superuser_is_refused(client, django_user_model):
    root = django_user_model.objects.create_superuser("root", "root@example.com", "x")
    client.force_login(root)
    root.is_active = False
    root.save()
    client.force_login(root)  # force_login refuses inactive users, so this stays anonymous
    assert client.get(reverse("admin:index")).status_code == 302


def test_anonymous_is_redirected_to_login(client):
    assert client.get(reverse("admin:index")).status_code == 302


def test_the_old_admin_url_is_gone(client):
    assert client.get("/admin/").status_code == 404
