"""
DRF permission class wired to the same `can()` helper the admin uses. No
DRF views exist yet in M1 (the API surface is M2), but this is written and
unit-tested now since it's the one seam both admin and future API must
share — see docs/architecture.md §11.
"""

from rest_framework.permissions import BasePermission

from .rbac import can


class CanPermission(BasePermission):
    """Set `required_action = "<app_label>.<codename>"` on the view, or
    override `get_required_action(request, view)` for per-method actions.
    """

    required_action: str | None = None

    def get_required_action(self, request, view) -> str:
        action = getattr(view, "required_action", None) or self.required_action
        if not action:
            raise ValueError(
                f"{view.__class__.__name__} must set `required_action` to use CanPermission"
            )
        return action

    def has_permission(self, request, view) -> bool:
        return can(request.user, self.get_required_action(request, view))

    def has_object_permission(self, request, view, obj) -> bool:
        return can(request.user, self.get_required_action(request, view), obj)
