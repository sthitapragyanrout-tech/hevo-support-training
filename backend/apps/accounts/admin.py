from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group

from .admin_mixins import CanPermissionAdminMixin
from .models import Role, RoleAssignment, User, UserIdentity
from .rbac import can

# Group carries no permissions and isn't used for anything yet (it's
# reserved for future org-unit isolation — see docs/architecture.md and the
# RBAC design discussion). An empty, unexplained admin section is just
# clutter; unregister it until isolation is actually built, then bring it
# back.
admin.site.unregister(Group)


class RoleAssignmentInline(admin.TabularInline):
    """Assign roles directly from the User page — the primary way to grant
    a role. The standalone RoleAssignmentAdmin screen still exists too, for
    bulk oversight (e.g. "show me everyone with the Mentor role").
    """

    model = RoleAssignment
    extra = 0

    def has_add_permission(self, request, obj):
        return can(request.user, "accounts.manage_roles")

    def has_change_permission(self, request, obj=None):
        return can(request.user, "accounts.manage_roles")

    def has_delete_permission(self, request, obj=None):
        return can(request.user, "accounts.manage_roles")

    def has_view_permission(self, request, obj=None):
        return can(request.user, "accounts.manage_roles")


@admin.register(User)
class UserAdmin(CanPermissionAdminMixin, DjangoUserAdmin):
    add_action = "accounts.manage_users"
    change_action = "accounts.manage_users"
    delete_action = "accounts.manage_users"

    # Pre-existing bug, found while testing this round of changes: Django's
    # default add_fieldsets only collects username/password1/password2 —
    # it never asks for `email`, even though our User model requires it
    # unique. Every admin-created user was silently getting email="",
    # which only breaks on the *second* such user (unique constraint
    # violation). Add `email` to the add form so it's collected upfront.
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "email", "password1", "password2")}),
    )

    # Django's default "Permissions" fieldset includes `groups` and
    # `user_permissions` — both dropped. Permissions only ever come from a
    # Role now (see accounts/rbac.py); showing a raw permission picker here
    # would contradict that and reintroduce the exact ambiguity the
    # Role-only design exists to avoid. `groups` is dropped alongside it
    # since Group itself is unregistered above — no point pointing a
    # control at a hidden, currently-empty model.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Hevo profile", {"fields": ("employee_id", "must_change_password", "timezone")}),
    )
    list_display = ("username", "email", "employee_id", "is_active", "is_staff")
    inlines = [RoleAssignmentInline]


@admin.register(UserIdentity)
class UserIdentityAdmin(CanPermissionAdminMixin, admin.ModelAdmin):
    add_action = "accounts.manage_users"
    change_action = "accounts.manage_users"
    delete_action = "accounts.manage_users"
    list_display = ("user", "provider", "external_id", "email")
    list_filter = ("provider",)


@admin.register(Role)
class RoleAdmin(CanPermissionAdminMixin, admin.ModelAdmin):
    add_action = "accounts.manage_roles"
    change_action = "accounts.manage_roles"
    delete_action = "accounts.manage_roles"
    list_display = ("name", "permission_count")
    filter_horizontal = ("permissions",)

    @admin.display(description="Permissions")
    def permission_count(self, obj: Role) -> int:
        return obj.permissions.count()


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(CanPermissionAdminMixin, admin.ModelAdmin):
    add_action = "accounts.manage_roles"
    change_action = "accounts.manage_roles"
    delete_action = "accounts.manage_roles"
    list_display = ("user", "role")
    list_filter = ("role",)
