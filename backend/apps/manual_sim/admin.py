from django.contrib import admin

from .models import MentorAssignment, RubricScore, SimCase, SimSubmission, SubmissionFile


class _ReadOnly(admin.ModelAdmin):
    """Emergency access only: simulations are rated, reassigned, extended and closed in the
    Admin Console, where every change is audited."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SimSubmission)
class SimSubmissionAdmin(_ReadOnly):
    list_display = ("case", "revision", "state", "routing", "late", "submitted_at", "rated_at")
    list_filter = ("state", "routing", "late")
    search_fields = ("case__user__email", "case__user__username")
    list_select_related = ("case__user", "case__activity")
    readonly_fields = [f.name for f in SimSubmission._meta.fields]


@admin.register(SimCase)
class SimCaseAdmin(_ReadOnly):
    list_display = ("user", "activity", "due_at", "due_basis", "closed_reason")
    list_filter = ("closed_reason", "due_basis")
    search_fields = ("user__email", "user__username")
    list_select_related = ("user", "activity")
    readonly_fields = [f.name for f in SimCase._meta.fields]


@admin.register(MentorAssignment)
class MentorAssignmentAdmin(_ReadOnly):
    list_display = ("learner", "course", "mentor", "source", "assigned_at")
    search_fields = ("learner__email", "mentor__email")
    list_select_related = ("learner", "mentor", "course")
    readonly_fields = [f.name for f in MentorAssignment._meta.fields]


@admin.register(RubricScore)
class RubricScoreAdmin(_ReadOnly):
    list_display = ("submission", "label", "score", "max_score")
    readonly_fields = [f.name for f in RubricScore._meta.fields]


@admin.register(SubmissionFile)
class SubmissionFileAdmin(_ReadOnly):
    list_display = ("original_name", "submission", "content_type", "size_bytes", "created_at")
    readonly_fields = [f.name for f in SubmissionFile._meta.fields]
