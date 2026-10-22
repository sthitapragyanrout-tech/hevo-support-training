"""
Custom ordering for the Django admin sidebar/app-index. Django's default is
alphabetical, which buries Catalog (the actual content-authoring tool) and
Accounts under "Authentication and Authorization" and Axes (login-lockout
logs — operational noise, not something a content author needs day to day).

Imported once from config/urls.py, before admin.site.urls is used.
"""

from django.contrib import admin

_APP_ORDER = ["catalog", "accounts", "auth", "axes"]


def _sort_key(app: dict) -> int:
    try:
        return _APP_ORDER.index(app["app_label"])
    except ValueError:
        return len(_APP_ORDER)


_original_get_app_list = admin.AdminSite.get_app_list


def _get_app_list(self, request, app_label=None):
    app_list = _original_get_app_list(self, request, app_label=app_label)
    return sorted(app_list, key=_sort_key)


admin.AdminSite.get_app_list = _get_app_list  # type: ignore[method-assign]


# Emergency access only: the Admin Console in the SPA is the way staff work
# now. Django Admin stays for break-glass use by active superusers, and is no
# longer opened to every `is_staff` account.
def _has_permission(self, request) -> bool:
    user = request.user
    return bool(user.is_active and user.is_superuser)


admin.AdminSite.has_permission = _has_permission  # type: ignore[method-assign]
admin.site.site_header = "Emergency back-office"
admin.site.site_title = "Emergency back-office"
admin.site.index_title = "Break-glass access — day-to-day work lives in the Admin Console"
