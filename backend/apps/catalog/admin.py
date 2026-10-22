from adminsortable2.admin import SortableAdminMixin
from django.contrib import admin, messages
from django.contrib.admin.views.main import ORDER_VAR, ChangeList
from django.core.exceptions import ValidationError
from django.db.models import BooleanField, Case, IntegerField, When
from django.urls import reverse
from django.utils.html import format_html
from django_json_widget.widgets import JSONEditorWidget

from apps.accounts.admin_mixins import CanPermissionAdminMixin

from .models import Activity, ContentNode, Course, CourseVersion


class ActivityInline(admin.StackedInline):
    """Stacked, not Tabular: the `config` JSON editor needs real width to
    be usable, and a TabularInline's horizontal table-column layout caps
    every field's width to its narrow table cell (measured at ~132px wide
    with 8 columns packed into one row) regardless of what width the
    widget itself asks for. Stacked lays out each Activity's fields
    vertically, one per line, so `config` gets the full form width.
    """

    model = Activity
    extra = 0

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "config":
            formfield.widget = JSONEditorWidget(width="100%", height="320px")
        return formfield


class _TreeOrderedChangeList(ChangeList):
    """Defaults the changelist to `_tree_rank` order instead of Django's
    normal `ModelAdmin.get_ordering()` -> `Meta.ordering` resolution.

    Deliberately *not* done by overriding `ModelAdmin.get_ordering()`
    itself: that method is also consulted by Django's unrelated
    `get_field_queryset()` (used to build FK-choice dropdowns for *other*
    admins referencing ContentNode, e.g. CourseVersionAdmin.root_node) —
    which applies the returned ordering to ContentNode's plain default
    manager, not to our annotated queryset. "_tree_rank" only exists as an
    annotation added in ContentNodeAdmin.get_queryset(), so that path would
    crash with "Cannot resolve keyword '_tree_rank' into field". Overriding
    ChangeList.get_ordering() instead only affects this changelist's own
    rendering. Clicking a column header (?o=...) still takes priority, via
    the same mechanism Django always uses — that's how drag-reorder stays
    reachable: click the "Sort" column to flip to flat `order` ordering,
    and SortableAdminMixin re-enables drag handles for that view.
    """

    def get_ordering(self, request, queryset):
        if ORDER_VAR in request.GET:
            return super().get_ordering(request, queryset)
        return self._get_deterministic_ordering(["_tree_rank"])


# Depth-based styling for the indented tree title — course reads as a
# heading, each level down gets progressively lighter/smaller.
_KIND_TITLE_STYLE: dict[str, str] = {
    ContentNode.Kind.COURSE: "font-weight:700; font-size:1.05em;",
    ContentNode.Kind.SEGMENT: "font-weight:600;",
    ContentNode.Kind.TOPIC: "font-weight:400;",
    ContentNode.Kind.SUBTOPIC: "font-weight:400; color:#5b6470;",
}

# What kind a "+ add child" link on a given row should create — a subtopic
# has no entry, since it can't parent another ContentNode (Activities hang
# off it instead, added from its own change page, not here).
_CHILD_KIND: dict[str, str] = {
    ContentNode.Kind.COURSE: ContentNode.Kind.SEGMENT,
    ContentNode.Kind.SEGMENT: ContentNode.Kind.TOPIC,
    ContentNode.Kind.TOPIC: ContentNode.Kind.SUBTOPIC,
}


@admin.register(ContentNode)
class ContentNodeAdmin(CanPermissionAdminMixin, SortableAdminMixin, admin.ModelAdmin):
    add_action = "catalog.author_content"
    change_action = "catalog.author_content"
    delete_action = "catalog.author_content"

    list_display = ("tree_title", "kind", "order", "course_version")
    list_filter = ("kind", "course_version")
    search_fields = ("title", "slug")
    inlines = [ActivityInline]

    # Not the default (Django auto-links the first list_display column to
    # the change page). tree_title's own HTML already contains <a> tags
    # (toggle, add-child) — Django wrapping the whole cell in another <a>
    # produces invalid nested anchors, which browsers "fix" by silently
    # mis-parsing/dropping content (confirmed: server HTML was correct,
    # the browser's *parsed* DOM was empty). `list_display_links = []`
    # does *not* turn this off (Django still falls back to linking the
    # first column) — pointing it at "kind" instead is what actually
    # avoids tree_title being auto-wrapped. tree_title links the title
    # text itself instead, at exactly one anchor level.
    list_display_links = ("kind",)

    class Media:
        css = {"all": ("catalog/admin/tree.css",)}
        js = ("catalog/admin/tree.js",)

    def get_queryset(self, request):
        """Annotate every row with its depth-first rank and depth in the
        tree, computed from a full parent/order snapshot walked in Python.

        `Meta.ordering = ["order", "id"]` only orders *siblings* relative
        to each other — it has no notion of parent/depth, so the changelist
        has never actually reflected course -> segment -> topic -> subtopic
        structure. This fixes the *default* ordering (see get_ordering()
        below) without touching how SortableAdminMixin's drag-reorder
        persists `order` itself.

        Fine at realistic course-tree scale (tens-to-low-hundreds of
        nodes) — the one extra query and the Case/When size both grow
        linearly with node count.
        """
        qs = super().get_queryset(request)

        nodes = list(ContentNode.objects.values("id", "parent_id", "order", "course_version_id"))
        children_by_parent: dict[int | None, list[dict]] = {}
        for n in nodes:
            children_by_parent.setdefault(n["parent_id"], []).append(n)
        for siblings in children_by_parent.values():
            siblings.sort(key=lambda n: n["order"])
        roots = sorted(
            children_by_parent.get(None, []),
            key=lambda n: (n["course_version_id"], n["order"]),
        )

        rank_by_id: dict[int, int] = {}
        depth_by_id: dict[int, int] = {}

        def walk(node: dict, depth: int) -> None:
            rank_by_id[node["id"]] = len(rank_by_id)
            depth_by_id[node["id"]] = depth
            for child in children_by_parent.get(node["id"], []):
                walk(child, depth + 1)

        for root in roots:
            walk(root, 0)

        rank_case = Case(
            *[When(pk=pk, then=rank) for pk, rank in rank_by_id.items()],
            output_field=IntegerField(),
        )
        depth_case = Case(
            *[When(pk=pk, then=depth) for pk, depth in depth_by_id.items()],
            output_field=IntegerField(),
        )
        has_children_ids = [pid for pid in children_by_parent if pid is not None]
        has_children_case = Case(
            *[When(pk=pk, then=True) for pk in has_children_ids],
            default=False,
            output_field=BooleanField(),
        )
        return qs.annotate(
            _tree_rank=rank_case, _tree_depth=depth_case, _has_children=has_children_case
        )

    def get_changelist(self, request, **kwargs):
        return _TreeOrderedChangeList

    @admin.display(description="Title")
    def tree_title(self, obj: ContentNode) -> str:
        depth = getattr(obj, "_tree_depth", 0)
        has_children = getattr(obj, "_has_children", False)
        style = _KIND_TITLE_STYLE.get(obj.kind, "")

        toggle_html = (
            format_html('<a href="#" class="tree-toggle" data-expanded="true">▼</a>')
            if has_children
            else format_html('<span class="tree-toggle-placeholder"></span>')
        )

        child_kind = _CHILD_KIND.get(obj.kind)
        if child_kind:
            add_url = (
                reverse("admin:catalog_contentnode_add")
                + f"?parent={obj.pk}&course_version={obj.course_version_id}&kind={child_kind}"
            )
            add_html = format_html(
                '<a href="{}" class="tree-add-child" title="Add {}">+</a>', add_url, child_kind
            )
        else:
            add_html = format_html("")

        change_url = reverse("admin:catalog_contentnode_change", args=[obj.pk])

        return format_html(
            '<span class="tree-node" data-pk="{}" data-parent-pk="{}" '
            'style="padding-left:{}px;">{}<a href="{}" style="{}">{}</a>{}</span>',
            obj.pk,
            obj.parent_id or "",
            depth * 24,
            toggle_html,
            change_url,
            style,
            obj.title,
            add_html,
        )

    # Published / in-review / archived versions are immutable: only a
    # superuser (emergency corrections) may touch their nodes from here.
    def _locked_for(self, request, obj) -> bool:
        return (
            obj is not None and not request.user.is_superuser and not obj.course_version.is_editable
        )

    def has_change_permission(self, request, obj=None):
        if self._locked_for(request, obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._locked_for(request, obj):
            return False
        return super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course_version" and not request.user.is_superuser:
            kwargs["queryset"] = CourseVersion.objects.filter(state=CourseVersion.State.DRAFT)
        if db_field.name == "parent":
            # Best-effort UX: a subtopic can never be anyone's parent, so
            # exclude it from the dropdown. Full dynamic filtering by the
            # currently-selected `kind` needs client-side JS and is out of
            # scope for M1 — the model's clean() is the real enforcement.
            kwargs["queryset"] = ContentNode.objects.exclude(kind=ContentNode.Kind.SUBTOPIC)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Course)
class CourseAdmin(CanPermissionAdminMixin, admin.ModelAdmin):
    """Back-office view of course identity. Day-to-day authoring happens in
    the Studio (React); this is for inspection and emergency corrections."""

    add_action = "catalog.author_content"
    change_action = "catalog.author_content"
    delete_action = "catalog.publish_courseversion"

    list_display = ("slug", "display_title", "created_by", "created_at", "archived_at")
    search_fields = ("slug",)

    @admin.display(description="Title")
    def display_title(self, obj: Course) -> str:
        return obj.title


@admin.register(CourseVersion)
class CourseVersionAdmin(CanPermissionAdminMixin, admin.ModelAdmin):
    change_action = "catalog.publish_courseversion"
    delete_action = "catalog.publish_courseversion"

    list_display = ("__str__", "course", "version", "state", "published_at", "published_by")
    list_filter = ("state",)
    actions = ["publish_selected"]

    @admin.action(description="Publish selected course version")
    def publish_selected(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, "Select exactly one course version to publish.", level=messages.ERROR
            )
            return
        course_version = queryset.first()
        try:
            course_version.publish(request.user)
        except ValidationError as exc:
            self.message_user(request, " ".join(exc.messages), level=messages.ERROR)
            return
        self.message_user(request, f"Published {course_version}.", level=messages.SUCCESS)
