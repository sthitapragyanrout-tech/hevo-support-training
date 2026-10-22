from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from apps.activities.registry import validate_config


class Course(models.Model):
    """Stable identity of a course across versions. Deliberately tiny:
    title and description are *versioned content* and live on each version's
    root ContentNode, so a learner pinned to v1 keeps v1's wording.
    """

    slug = models.SlugField(max_length=255, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.title or self.slug

    @property
    def title(self) -> str:
        """Display title: the newest version's root title."""
        version = self.versions.select_related("root_node").order_by("-version").first()
        return version.root_node.title if version and version.root_node else ""


class CourseVersion(models.Model):
    """One snapshot of a course's content tree. Enrollments (later) pin a
    *version*, so publishing a new one cannot change an in-flight cohort.
    Published versions are immutable; authors edit the course's single open
    draft (`draft` → `in_review` → `published`).
    """

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    # States in which a course may have at most one version.
    OPEN_STATES = (State.DRAFT, State.IN_REVIEW)

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="versions")

    # Nullable: a CourseVersion is created first, then its root ContentNode
    # is created pointing back at it via ContentNode.course_version, then
    # this field is backfilled to that root node.
    root_node = models.OneToOneField(
        "ContentNode",
        on_delete=models.PROTECT,
        related_name="as_course_root",
        null=True,
        blank=True,
    )
    version = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        permissions = [
            ("publish_courseversion", "Can publish a course version"),
        ]
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "version"], name="uniq_course_version_number"
            ),
            # At most one open (draft / in-review) version per course.
            models.UniqueConstraint(
                fields=["course"],
                condition=models.Q(state__in=["draft", "in_review"]),
                name="uniq_open_version_per_course",
            ),
        ]

    def __str__(self) -> str:
        title = self.root_node.title if self.root_node else "(no root yet)"
        return f"{title} v{self.version} [{self.state}]"

    @property
    def is_editable(self) -> bool:
        """Only a plain draft is editable; in-review and published are locked."""
        return self.state == self.State.DRAFT

    def publish(self, by_user) -> None:
        """Publish this version and archive the course's previously
        published one (it stays readable for anyone pinned to it).
        """
        if self.state not in self.OPEN_STATES:
            raise ValidationError(
                f"A {self.get_state_display().lower()} version can't be published."
            )
        with transaction.atomic():
            CourseVersion.objects.filter(course=self.course, state=self.State.PUBLISHED).exclude(
                pk=self.pk
            ).update(state=self.State.ARCHIVED)
            self.state = self.State.PUBLISHED
            self.published_at = timezone.now()
            self.published_by = by_user
            self.full_clean()
            self.save(update_fields=["state", "published_at", "published_by"])


class ContentNode(models.Model):
    """Self-referencing course tree: course -> segment -> topic -> subtopic,
    arbitrary depth in principle, but M1 seeds exactly these four kinds per
    the allowed-parent map below. Adding a level or reordering a course is
    data, not a migration.
    """

    class Kind(models.TextChoices):
        COURSE = "course", "Course"
        SEGMENT = "segment", "Segment"
        TOPIC = "topic", "Topic"
        SUBTOPIC = "subtopic", "Subtopic"

    # None means "must be a root node" (parent must be null).
    ALLOWED_PARENT_KIND: dict[str, str | None] = {
        Kind.COURSE: None,
        Kind.SEGMENT: Kind.COURSE,
        Kind.TOPIC: Kind.SEGMENT,
        Kind.SUBTOPIC: Kind.TOPIC,
    }

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    course_version = models.ForeignKey(
        CourseVersion, on_delete=models.CASCADE, related_name="nodes"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    estimated_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        permissions = [
            ("author_content", "Can author course content (nodes and activities)"),
        ]
        unique_together = [("parent", "slug")]
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind})"

    def clean(self):
        if (
            self.parent_id
            and self.course_version_id
            and (self.parent.course_version_id != self.course_version_id)
        ):
            raise ValidationError({"parent": "A node's parent must be in the same course version."})
        if self.kind not in self.ALLOWED_PARENT_KIND:
            return  # field-level validation already flags a missing/invalid kind
        expected_parent_kind = self.ALLOWED_PARENT_KIND[self.kind]
        if expected_parent_kind is None:
            if self.parent is not None:
                raise ValidationError(
                    {"parent": f"A '{self.kind}' node must be a root node (no parent)."}
                )
        else:
            if self.parent is None or self.parent.kind != expected_parent_kind:
                raise ValidationError(
                    {
                        "parent": (
                            f"A '{self.kind}' node must have a parent "
                            f"of kind '{expected_parent_kind}'."
                        )
                    }
                )


class Activity(models.Model):
    """One learnable unit hanging off a ContentNode. `activity_type` keys the
    type registry in `apps/activities/registry.py` (label, config schema,
    defaults). `provider` (M4) and `rubric` (M5) FKs are deliberately not
    added yet — they arrive as plain additive nullable-FK migrations when
    their owning apps exist.
    """

    class ActivityType(models.TextChoices):
        READING = "reading", "Reading"
        VIDEO = "video", "Video"
        PDF = "pdf", "PDF"
        MCQ = "mcq", "MCQ / quiz"
        WORKSHOP = "workshop", "Hands-on workshop"
        EXTERNAL_COURSE = "external_course", "External course"
        MANUAL_SIM = "manual_sim", "Manual simulation"
        BOT_SIM = "bot_sim", "Bot simulation"

    content_node = models.ForeignKey(
        ContentNode, on_delete=models.CASCADE, related_name="activities"
    )
    activity_type = models.CharField(max_length=32, choices=ActivityType.choices)
    title = models.CharField(max_length=255)
    config = models.JSONField(default=dict, blank=True)
    is_required = models.BooleanField(default=True)
    max_attempts = models.PositiveIntegerField(default=3)
    mastery_threshold = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    points = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.title} ({self.activity_type})"

    def clean(self):
        # Strict: a full_clean()'d activity must have a complete config.
        # (The authoring API validates leniently while a draft is in progress.)
        errors = validate_config(self.activity_type, self.config, strict=True)
        if errors:
            raise ValidationError({"config": errors[0]})


# MediaAsset (`→uploaded_by`, `kind`, `original_path`, `hls_manifest_path`,
# `duration_seconds`, `transcode_state`, `checksum`) is deliberately NOT
# defined here in M1: no upload UI, no ffmpeg task, and no plugin reads it
# yet, so an empty table would just be dead weight with nothing to test.
# Add it as a real model when M3 (media pipeline) needs it. See
# docs/architecture.md §5 and the M1 plan's "critical files" note.
