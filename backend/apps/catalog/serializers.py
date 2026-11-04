from rest_framework import serializers

from apps.activities.registry import is_completable, learner_config, validate_config

from .models import Activity, ContentNode, CourseVersion


class ActivitySummarySerializer(serializers.ModelSerializer):
    """The learner's view of an activity. `config` is an allow-list per type
    (see `registry.learner_config`): a reading's link yes, a quiz's answer key
    never. `completable` says whether the learner can finish it today."""

    config = serializers.SerializerMethodField()
    completable = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "id",
            "activity_type",
            "title",
            "is_required",
            "points",
            "order",
            "max_attempts",
            "config",
            "completable",
        ]

    def get_config(self, obj: Activity) -> dict:
        return learner_config(obj.activity_type, obj.config)

    def get_completable(self, obj: Activity) -> bool:
        return is_completable(obj.activity_type, obj.config)


class AuthoringActivitySerializer(serializers.ModelSerializer):
    """What an author sees: the full config, plus whether it still needs setup."""

    needs_setup = serializers.SerializerMethodField()
    completable = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "id",
            "activity_type",
            "title",
            "config",
            "completable",
            "is_required",
            "points",
            "max_attempts",
            "mastery_threshold",
            "order",
            "needs_setup",
        ]

    def get_completable(self, obj: Activity) -> bool:
        return is_completable(obj.activity_type, obj.config)

    def get_needs_setup(self, obj: Activity) -> bool:
        return bool(validate_config(obj.activity_type, obj.config, strict=True))


class CourseSummarySerializer(serializers.ModelSerializer):
    """One row in the learner's course list. The title/description live on
    the root ContentNode, not on CourseVersion itself.
    """

    title = serializers.CharField(source="root_node.title")
    description = serializers.CharField(source="root_node.description")

    class Meta:
        model = CourseVersion
        fields = ["id", "course_id", "title", "description", "version", "published_at"]


def build_course_tree(course_version: CourseVersion, *, authoring: bool = False) -> dict:
    """Assemble the nested tree in Python from two queries (all nodes +
    their activities) instead of a recursive serializer, which would issue
    one query per node. Node counts are tens to low hundreds, so a single
    payload is the right shape for a sidebar-style tree UI.

    `authoring=True` is for the Studio only: it includes each activity's
    `config` (never sent to learners — an MCQ's config holds the answers)
    and each node's `order`/`slug`.
    """
    activity_serializer = AuthoringActivitySerializer if authoring else ActivitySummarySerializer
    nodes = list(
        ContentNode.objects.filter(course_version=course_version).prefetch_related("activities")
    )  # Meta.ordering = ["order", "id"] already orders siblings

    by_parent: dict[int | None, list[dict]] = {}
    root: dict | None = None
    for node in nodes:
        payload = {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            "slug": node.slug,
            "description": node.description,
            "is_required": node.is_required,
            "estimated_minutes": node.estimated_minutes,
            "activities": activity_serializer(node.activities.all(), many=True).data,
            "children": [],
        }
        if authoring:
            payload["order"] = node.order
        by_parent.setdefault(node.parent_id, []).append(payload)
        if node.id == course_version.root_node_id:
            root = payload

    def attach(payload: dict) -> None:
        payload["children"] = by_parent.get(payload["id"], [])
        for child in payload["children"]:
            attach(child)

    if root is not None:
        attach(root)

    return {
        "id": course_version.id,
        "course_id": course_version.course_id,
        "version": course_version.version,
        "published_at": course_version.published_at,
        "learning_order": course_version.learning_order,
        "root": root,
    }
