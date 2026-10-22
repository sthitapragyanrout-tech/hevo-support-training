"""
Shared ModelAdmin mixin so every admin authorization decision funnels
through `can()` — the same helper DRF permission classes use — instead of
Django's default per-instance `has_perm`. See docs/architecture.md §11.
"""

from .rbac import can


class CanPermissionAdminMixin:
    """Set `add_action`/`change_action`/`delete_action`/`view_action` on the
    ModelAdmin to the permission codename each maps to. Any left unset falls
    back to Django's default admin behaviour for that action.
    """

    add_action: str | None = None
    change_action: str | None = None
    delete_action: str | None = None
    view_action: str | None = None

    def has_add_permission(self, request):
        if self.add_action:
            return can(request.user, self.add_action)
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self.change_action:
            return can(request.user, self.change_action, obj)
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self.delete_action:
            return can(request.user, self.delete_action, obj)
        return super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        if self.view_action:
            return can(request.user, self.view_action, obj)
        return super().has_view_permission(request, obj)
