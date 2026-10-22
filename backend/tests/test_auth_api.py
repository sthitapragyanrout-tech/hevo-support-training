import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="learner1", email="learner1@example.com", password="testpass123"
    )


class TestSessionView:
    def test_anonymous_session(self, client):
        response = client.get(reverse("accounts_api:session"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": False, "user": None}

    def test_sets_csrf_cookie(self, client):
        response = client.get(reverse("accounts_api:session"))
        assert "csrftoken" in response.cookies


class TestLoginView:
    def test_login_with_username(self, client, user):
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["user"]["username"] == "learner1"

    def test_login_with_email(self, client, user):
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "learner1@example.com", "password": "testpass123"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "learner1@example.com"

    def test_login_wrong_password(self, client, user):
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "wrong"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_login_unknown_user(self, client):
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "nobody", "password": "whatever"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_login_inactive_user(self, client, user):
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_session_reflects_login(self, client, user):
        client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        response = client.get(reverse("accounts_api:session"))
        body = response.json()
        assert body["authenticated"] is True
        assert body["user"]["username"] == "learner1"

    def test_roles_included_in_user_payload(self, client, user):
        from apps.accounts.models import Role, RoleAssignment

        role = Role.objects.get_or_create(name=Role.Name.TRAINER)[0]
        RoleAssignment.objects.create(user=user, role=role)

        client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        response = client.get(reverse("accounts_api:session"))
        assert response.json()["user"]["roles"] == ["trainer"]


class TestLogoutView:
    def test_logout_requires_auth(self, client):
        # DRF + SessionAuthentication returns 403 (not 401) for anonymous
        # requests to an IsAuthenticated view — no WWW-Authenticate header
        # to justify a 401 challenge.
        response = client.post(reverse("accounts_api:logout"))
        assert response.status_code == 403

    def test_logout_clears_session(self, client, user):
        client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        response = client.post(reverse("accounts_api:logout"))
        assert response.status_code == 204

        session_response = client.get(reverse("accounts_api:session"))
        assert session_response.json()["authenticated"] is False


class TestCsrfEnforcement:
    """The Django test client disables CSRF checks by default — these
    tests explicitly turn it back on to prove the real browser flow (GET
    /session/ for a cookie, then send it back as a header) actually works,
    not just that the view logic is correct in isolation.

    DRF's SessionAuthentication only enforces CSRF once a session already
    identifies a user (see its own "Unauthenticated, CSRF validation not
    required" comment) — there's no existing session to protect on the
    anonymous login request itself, so DRF deliberately does not require a
    CSRF token there (confirmed against DRF's source, not assumed). The
    security-relevant case is the *authenticated* one: once a session
    exists, an action like logout must not be forgeable cross-site — that's
    what's actually worth proving here.
    """

    def test_login_without_csrf_token_still_succeeds(self, user):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_authenticated_action_without_csrf_token_is_rejected(self, user):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
        )
        # Now that a session exists, logout (an IsAuthenticated view) must
        # require a valid CSRF token — this is the case DRF actually
        # protects.
        response = strict_client.post(reverse("accounts_api:logout"))
        assert response.status_code == 403

    def test_authenticated_action_with_csrf_token_succeeds(self, user):
        strict_client = Client(enforce_csrf_checks=True)
        session_response = strict_client.get(reverse("accounts_api:session"))
        csrf_token = session_response.cookies["csrftoken"].value

        login_response = strict_client.post(
            reverse("accounts_api:login"),
            {"login": "learner1", "password": "testpass123"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        # Django rotates the CSRF token on login (session-fixation
        # defense) — the pre-login token above is now stale; pick up the
        # rotated one the login response actually set.
        csrf_token = login_response.cookies["csrftoken"].value

        response = strict_client.post(
            reverse("accounts_api:logout"), HTTP_X_CSRFTOKEN=csrf_token
        )
        assert response.status_code == 204
