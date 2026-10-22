"""Introduce `Course` (stable identity across versions), the `in_review`
state and the one-open-version-per-course rule.

Three steps so existing rows survive: (1) create Course + nullable FK,
(2) backfill — every existing CourseVersion becomes its own Course (there is
no prior link between versions, so none can be inferred), (3) tighten the FK
and add the constraints.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def backfill_courses(apps, schema_editor):
    Course = apps.get_model("catalog", "Course")
    CourseVersion = apps.get_model("catalog", "CourseVersion")

    taken = set(Course.objects.values_list("slug", flat=True))
    for version in CourseVersion.objects.filter(course__isnull=True).select_related("root_node"):
        base = slugify(version.root_node.title) if version.root_node else ""
        base = base or f"course-{version.pk}"
        slug, n = base, 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1
        taken.add(slug)
        course = Course.objects.create(slug=slug)
        version.course = course
        version.save(update_fields=["course"])


def unlink_courses(apps, schema_editor):
    # Reverse: nothing to restore — the FK column is dropped by the schema ops.
    pass


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Course",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddField(
            model_name="courseversion",
            name="course",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="versions",
                to="catalog.course",
            ),
        ),
        migrations.AddField(
            model_name="courseversion",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="courseversion",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="courseversion",
            name="state",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("in_review", "In review"),
                    ("published", "Published"),
                    ("archived", "Archived"),
                ],
                default="draft",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_courses, unlink_courses),
        migrations.AlterField(
            model_name="courseversion",
            name="course",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="versions",
                to="catalog.course",
            ),
        ),
        migrations.AddConstraint(
            model_name="courseversion",
            constraint=models.UniqueConstraint(fields=("course", "version"), name="uniq_course_version_number"),
        ),
        migrations.AddConstraint(
            model_name="courseversion",
            constraint=models.UniqueConstraint(
                condition=models.Q(("state__in", ["draft", "in_review"])),
                fields=("course",),
                name="uniq_open_version_per_course",
            ),
        ),
    ]
