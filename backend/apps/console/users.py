"""Users: find them, create them, edit them, give them roles, reset their
password, unlock them. Each write is checked against `can()` and logged."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import admin_services as svc
from apps.accounts.rbac import can
from apps.audit import services as audit

from .base import ConsoleView, paginate

User = get_user_model()

MANAGE_USERS = "accounts.manage_users"
MANAGE_ROLES = "accounts.manage_roles"


def user_row(user, locked: set[str]) -> dict[str, Any]:
    return {
        "id": user.pk,
        "name": svc.display_name(user),
        "email": user.email,
        "username": user.username,
        "employee_id": user.employee_id,
        "is_active": user.is_active,
        "roles": svc.role_names(user),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "locked": user.username in locked,
        "must_change_password": user.must_change_password,
    }


def user_detail(user, viewer) -> dict[str, Any]:
    return {
        **user_row(user, svc.locked_usernames()),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "timezone": user.timezone,
        "date_joined": user.date_joined.isoformat(),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        # Only a superuser may change those two; the screen shows them either way.
        "can_edit_privileges": bool(viewer.is_superuser),
        "is_self": user.pk == viewer.pk,
        "identities": [
            {"provider": i.provider, "external_id": i.external_id, "email": i.email}
            for i in user.identities.all()
        ],
    }


class UserListView(ConsoleView):
    required_action = MANAGE_USERS

    def get(self, request: Request) -> Response:
        params = request.query_params
        qs = svc.list_users(
            search=params.get("search", "").strip(),
            role=params.get("role", ""),
            active=params.get("active", ""),
            locked=params.get("locked", ""),
            ordering=params.get("ordering", "name"),
        )
        page, meta = paginate(request, qs)
        locked = svc.locked_usernames()
        return Response({"results": [user_row(u, locked) for u in page], **meta})

    class CreateSerializer(serializers.Serializer):
        email = serializers.EmailField()
        username = serializers.CharField(required=False, allow_blank=True, max_length=150)
        first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
        last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
        employee_id = serializers.CharField(
            required=False, allow_blank=True, allow_null=True, max_length=32
        )
        timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
        password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
        roles = serializers.ListField(child=serializers.CharField(), required=False)

    def post(self, request: Request) -> Response:
        data = self.CreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if "roles" in values and not can(request.user, MANAGE_ROLES):
            raise PermissionDenied("You can’t assign roles.")
        user, generated = svc.create_user(
            email=values["email"],
            username=values.get("username", ""),
            first_name=values.get("first_name", ""),
            last_name=values.get("last_name", ""),
            employee_id=values.get("employee_id"),
            timezone_name=values.get("timezone") or None,
            password=values.get("password", ""),
            roles=values.get("roles"),
        )
        audit.record(
            request,
            "users.create",
            target_type="user",
            target_id=user.pk,
            target_label=user.email,
            changes={"email": user.email, "roles": svc.role_names(user)},
        )
        body = user_detail(user, request.user)
        if generated:
            body["temporary_password"] = generated  # shown once, never stored in the log
        return Response(body, status=status.HTTP_201_CREATED)


class UserDetailView(ConsoleView):
    required_action = MANAGE_USERS

    def get(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User.objects.prefetch_related("identities"), pk=user_id)
        return Response(user_detail(user, request.user))

    class UpdateSerializer(serializers.Serializer):
        first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
        last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
        email = serializers.EmailField(required=False)
        employee_id = serializers.CharField(
            required=False, allow_blank=True, allow_null=True, max_length=32
        )
        timezone = serializers.CharField(required=False, max_length=64)
        must_change_password = serializers.BooleanField(required=False)
        is_active = serializers.BooleanField(required=False)
        is_staff = serializers.BooleanField(required=False)
        is_superuser = serializers.BooleanField(required=False)

    def patch(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        data = self.UpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        diff = svc.update_user(request.user, user, dict(data.validated_data))
        # Turning an account off or on is its own, easy-to-find kind of event.
        if "is_active" in diff:
            action = "users.reactivate" if user.is_active else "users.deactivate"
            audit.record(
                request,
                action,
                target_type="user",
                target_id=user.pk,
                target_label=user.email,
            )
        rest = {k: v for k, v in diff.items() if k != "is_active"}
        if rest:
            audit.record(
                request,
                "users.update",
                target_type="user",
                target_id=user.pk,
                target_label=user.email,
                changes=rest,
            )
        return Response(user_detail(user, request.user))


class SetPasswordView(ConsoleView):
    required_action = MANAGE_USERS

    class Serializer(serializers.Serializer):
        password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    def post(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        generated = svc.set_password(user, data.validated_data.get("password", ""))
        audit.record(
            request,
            "users.set_password",
            target_type="user",
            target_id=user.pk,
            target_label=user.email,
            changes={"generated": generated is not None, "must_change_password": True},
        )
        return Response({"temporary_password": generated} if generated else {"ok": True})


class UnlockView(ConsoleView):
    required_action = MANAGE_USERS

    def post(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        removed = svc.unlock(user)
        audit.record(
            request,
            "users.unlock",
            target_type="user",
            target_id=user.pk,
            target_label=user.email,
            changes={"failed_attempts_cleared": removed},
        )
        return Response({"cleared": removed})


class UserRolesView(ConsoleView):
    required_action = MANAGE_ROLES

    class Serializer(serializers.Serializer):
        roles = serializers.ListField(child=serializers.CharField())

    def put(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        change = svc.set_roles(request.user, user, data.validated_data["roles"])
        if change["before"] != change["after"]:
            audit.record(
                request,
                "users.set_roles",
                target_type="user",
                target_id=user.pk,
                target_label=user.email,
                changes=change,
            )
        return Response({"roles": change["after"]})
