from django.contrib import admin

from .models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    """Back-office inspection of uploaded videos. Uploading and retrying happen
    in the Studio; nothing here edits a file or its state."""

    list_display = ("original_name", "status", "uploaded_by", "duration_seconds", "created_at")
    list_filter = ("status",)
    search_fields = ("original_name", "uploaded_by__email", "uploaded_by__username")
    list_select_related = ("uploaded_by",)
    readonly_fields = [f.name for f in MediaAsset._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
