from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit

from .models import User
from .serializers import LoginSerializer, UserSerializer


@method_decorator(ensure_csrf_cookie, name="get")
class SessionView(APIView):
    """GET /api/v1/auth/session/ — always 200, authenticated or not.

    The SPA calls this once on load: it's how a page refresh recovers
    "am I logged in" state, and — via `ensure_csrf_cookie` — how it gets a
    csrftoken cookie set *before* it ever needs to POST to /login/ (Django's
    CSRF middleware requires a valid token on every unsafe-method request,
    including the login request itself).
    """

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        if request.user.is_authenticated:
            return Response({"authenticated": True, "user": UserSerializer(request.user).data})
        return Response({"authenticated": False, "user": None})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["login"]
        password = serializer.validated_data["password"]

        # `email` is the real-world identity (per docs/architecture.md
        # §11), but Django's auth machinery (and django-axes' lockout
        # tracking) is keyed on `username` — resolve email -> username
        # here, once, rather than touching the auth backend stack.
        user_obj = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()
        username = user_obj.username if user_obj else identifier

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            return Response(
                {"detail": "This account is inactive."}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request, user)
        return Response({"user": UserSerializer(user).data})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    """POST /api/v1/auth/password/ — a signed-in person changes their own
    password. It re-checks the current one (through `authenticate`, so django-axes
    counts wrong guesses and a hijacked session can't brute-force it), applies
    the same strength rules as everywhere, and clears "must change password".
    The session stays signed in; any other session ends, because the session
    hash changes with the password."""

    permission_classes = [IsAuthenticated]

    class Serializer(serializers.Serializer):
        current_password = serializers.CharField(trim_whitespace=False)
        new_password = serializers.CharField(trim_whitespace=False)

    def post(self, request: Request) -> Response:
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        current = data.validated_data["current_password"]
        new = data.validated_data["new_password"]
        user = request.user
        assert isinstance(user, User)  # IsAuthenticated: never anonymous

        if authenticate(request, username=user.username, password=current) is None:
            return Response(
                {"detail": "Your current password isn’t right."}, status=status.HTTP_400_BAD_REQUEST
            )
        if new == current:
            return Response(
                {"detail": "Choose a password that’s different from your current one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new, user)
        except ValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        audit.record(
            request,
            "account.change_password",
            target_type="user",
            target_id=user.pk,
            target_label=user.email,
        )
        return Response({"user": UserSerializer(user).data})
