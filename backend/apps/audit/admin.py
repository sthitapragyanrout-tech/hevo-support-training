from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only. The Admin Console is the way to browse it; this exists so
    the emergency back-office can still inspect it."""

    list_display = ("created_at", "actor_label", "action", "target_label")
    list_filter = ("action",)
    search_fields = ("actor_label", "action", "target_label")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
