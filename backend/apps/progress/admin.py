from django.contrib import admin

from .models import ActivityAttempt, ActivityProgress, LessonCompletion, VideoWatch


@admin.register(ActivityProgress)
class ActivityProgressAdmin(admin.ModelAdmin):
    """Back-office inspection only; progress is recorded by learners in the app."""

    list_display = ("user", "activity", "state", "started_at", "completed_at")
    list_filter = ("state",)
    search_fields = ("user__username", "user__email", "activity__title")
    list_select_related = ("user", "activity")

    def has_add_permission(self, request):
        return False


@admin.register(LessonCompletion)
class LessonCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "node", "completed_at", "provisional")
    list_filter = ("provisional",)
    search_fields = ("user__username", "user__email", "node__title")
    list_select_related = ("user", "node")

    def has_add_permission(self, request):
        return False


@admin.register(ActivityAttempt)
class ActivityAttemptAdmin(admin.ModelAdmin):
    """Read-only record of scored tries. Deleting a learner's attempts here is
    how their attempts are reset until trainers get a screen for it (a
    learner who has already passed also needs their progress row removed)."""

    list_display = ("user", "activity", "number", "score", "passed", "submitted_at")
    list_filter = ("passed",)
    search_fields = ("user__username", "user__email", "activity__title")
    list_select_related = ("user", "activity")
    readonly_fields = (
        "user",
        "activity",
        "number",
        "answers",
        "details",
        "score",
        "passed",
        "submitted_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(VideoWatch)
class VideoWatchAdmin(admin.ModelAdmin):
    """Read-only record of verified watching, with anything flagged for review."""

    list_display = ("user", "activity", "credited_seconds", "needs_review", "completed_at")
    list_filter = ("needs_review", "fidelity")
    search_fields = ("user__username", "user__email", "activity__title")
    list_select_related = ("user", "activity")
    readonly_fields = [f.name for f in VideoWatch._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
