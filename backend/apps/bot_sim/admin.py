from django.contrib import admin

from .models import LLMCall, Scenario, SimSession


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    """Emergency access only: scenarios are written, reviewed and approved in the
    Admin Console (Practice scenarios), where every change is audited."""

    list_display = ("issue_summary", "topic", "persona_type", "status", "source", "created_at")
    list_filter = ("status", "topic", "persona_type", "source")
    search_fields = ("issue_summary", "opening_message")
    readonly_fields = [f.name for f in Scenario._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SimSession)
class SimSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "activity", "state", "preview", "started_at", "tokens_used")
    list_filter = ("state", "preview")
    search_fields = ("user__email", "user__username")
    list_select_related = ("user", "activity")
    readonly_fields = [f.name for f in SimSession._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "task",
        "model",
        "status",
        "tokens_in",
        "tokens_out",
        "latency_ms",
    )
    list_filter = ("task", "status")
    readonly_fields = [f.name for f in LLMCall._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
