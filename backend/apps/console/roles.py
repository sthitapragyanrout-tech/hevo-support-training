"""Roles: what each role may do, as a matrix; change it with safeguards."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import admin_services as svc
from apps.accounts.models import Role
from apps.audit import services as audit

from .base import ConsoleView

MANAGE_ROLES = "accounts.manage_roles"
MANAGE_USERS = "accounts.manage_users"


class RoleListView(ConsoleView):
    required_action = MANAGE_ROLES

    def get(self, request: Request) -> Response:
        return Response(svc.role_matrix())


class RoleCreateView(ConsoleView):
    required_action = MANAGE_ROLES

    class Serializer(serializers.Serializer):
        name = serializers.CharField(max_length=200, allow_blank=True)
        permissions = serializers.ListField(child=serializers.CharField(), required=False)

    def post(self, request: Request) -> Response:
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        role = svc.create_role(data.validated_data["name"], data.validated_data.get("permissions"))
        audit.record(
            request,
            "roles.create",
            target_type="role",
            target_id=role.pk,
            target_label=role.display_label,
            changes={"name": role.name, "permissions": data.validated_data.get("permissions", [])},
        )
        row = next(r for r in svc.role_matrix()["roles"] if r["id"] == role.pk)
        return Response(row, status=status.HTTP_201_CREATED)


class RoleDetailView(ConsoleView):
    required_action = MANAGE_ROLES

    class Serializer(serializers.Serializer):
        name = serializers.CharField(max_length=200, allow_blank=True)

    def patch(self, request: Request, role_id: int) -> Response:
        role = get_object_or_404(Role, pk=role_id)
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        change = svc.rename_role(role, data.validated_data["name"])
        if change["before"] != change["after"]:
            audit.record(
                request,
                "roles.rename",
                target_type="role",
                target_id=role.pk,
                target_label=role.display_label,
                changes=change,
            )
        return Response(next(r for r in svc.role_matrix()["roles"] if r["id"] == role.pk))

    def delete(self, request: Request, role_id: int) -> Response:
        role = get_object_or_404(Role, pk=role_id)
        target_id, label = role.pk, role.display_label
        snapshot = svc.delete_role(role)
        audit.record(
            request,
            "roles.delete",
            target_type="role",
            target_id=target_id,
            target_label=label,
            changes=snapshot,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleOptionsView(ConsoleView):
    """Every role's name and label — for the pickers on the Users screens, so
    anyone who manages users (not only roles) can see what to choose from."""

    required_any = (MANAGE_USERS, MANAGE_ROLES)

    def get(self, request: Request) -> Response:
        return Response({"results": svc.role_options()})


class RolePermissionsView(ConsoleView):
    required_action = MANAGE_ROLES

    class Serializer(serializers.Serializer):
        permissions = serializers.ListField(child=serializers.CharField())

    def put(self, request: Request, role_id: int) -> Response:
        role = get_object_or_404(Role, pk=role_id)
        data = self.Serializer(data=request.data)
        data.is_valid(raise_exception=True)
        change = svc.set_role_permissions(role, data.validated_data["permissions"])
        if change["before"] != change["after"]:
            audit.record(
                request,
                "roles.set_permissions",
                target_type="role",
                target_id=role.pk,
                target_label=role.display_label,
                changes=change,
            )
        return Response(next(r for r in svc.role_matrix()["roles"] if r["id"] == role.pk))
