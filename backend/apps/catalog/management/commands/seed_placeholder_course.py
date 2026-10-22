"""
PLACEHOLDER DATA — invented pending real spreadsheets, see
docs/architecture.md §16 Q1 ("copy the two reference spreadsheets into the
working directory and the real hierarchy/weights get parsed into fixtures").

Builds an illustrative CX Onboarding course tree via the ORM (readable,
easy to hand-edit, no fragile hardcoded PKs) so the admin has something
real to author/reorder/publish against. Run once, then
`manage.py dumpdata catalog --natural-foreign --natural-primary` to freeze
it into `apps/catalog/fixtures/placeholder_course_tree.json` — that fixture,
not this command, is what `make seed` actually loads day to day.

NOTE: the fixture has since been hand-edited with realistic sample lesson
content (Markdown descriptions, durations) for the learner UI, so it is the
source of truth and this command's tree is intentionally *not* kept in sync.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Activity, ContentNode, Course, CourseVersion

PLACEHOLDER_TAG = " [PLACEHOLDER]"

TREE = {
    "title": "CX Onboarding 2026",
    "segments": [
        {
            "title": "Product Fundamentals",
            "topics": [
                {
                    "title": "Pipeline Concepts",
                    "subtopics": [
                        {
                            "title": "Sources & Destinations",
                            "activities": [
                                (
                                    Activity.ActivityType.READING,
                                    "Sources & Destinations overview",
                                    {
                                        "source_url": "https://docs.hevo.example/sources",
                                        "estimated_read_minutes": 15,
                                    },
                                ),
                                (
                                    Activity.ActivityType.MCQ,
                                    "Sources & Destinations quiz",
                                    {
                                        "questions": [
                                            {
                                                "text": "What is a source?",
                                                "choices": ["A", "B"],
                                                "answer": 0,
                                            }
                                        ],
                                        "pass_threshold": 0.8,
                                    },
                                ),
                            ],
                        },
                        {
                            "title": "Ingestion Modes",
                            "activities": [
                                (
                                    Activity.ActivityType.VIDEO,
                                    "Ingestion Modes walkthrough",
                                    {
                                        "video_asset_ref": "placeholder-ingestion-modes",
                                        "completion_threshold": 0.9,
                                        "max_credited_rate": 1.0,
                                    },
                                ),
                            ],
                        },
                    ],
                },
                {
                    "title": "Transformations",
                    "subtopics": [
                        {
                            "title": "Basic Transformations",
                            "activities": [
                                (
                                    Activity.ActivityType.READING,
                                    "Basic Transformations guide",
                                    {
                                        "source_url": "https://docs.hevo.example/transformations",
                                        "estimated_read_minutes": 20,
                                    },
                                ),
                            ],
                        },
                        {
                            "title": "Advanced Transformations",
                            "activities": [
                                (
                                    Activity.ActivityType.EXTERNAL_COURSE,
                                    "Scaler: Advanced SQL Transformations",
                                    {
                                        "provider_name": "Scaler",
                                        "course_url": "https://scaler.example/advanced-sql",
                                        "requires_verification": True,
                                    },
                                ),
                            ],
                        },
                    ],
                },
            ],
        },
        {
            "title": "Troubleshooting Basics",
            "topics": [
                {
                    "title": "Common Failures",
                    "subtopics": [
                        {
                            "title": "Ingestion Failures",
                            "activities": [
                                (
                                    Activity.ActivityType.READING,
                                    "Ingestion failure playbook",
                                    {
                                        "source_url": "https://docs.hevo.example/ingestion-failures",
                                        "estimated_read_minutes": 25,
                                    },
                                ),
                            ],
                        },
                        {
                            "title": "Load Failures",
                            "activities": [
                                (
                                    Activity.ActivityType.MCQ,
                                    "Load failures quiz",
                                    {
                                        "questions": [
                                            {
                                                "text": "What causes a load failure?",
                                                "choices": ["A", "B", "C"],
                                                "answer": 2,
                                            }
                                        ],
                                        "pass_threshold": 0.8,
                                    },
                                ),
                            ],
                        },
                    ],
                },
                {
                    "title": "Debugging Tools",
                    "subtopics": [
                        {
                            "title": "Log Analysis",
                            "activities": [
                                (
                                    Activity.ActivityType.VIDEO,
                                    "Log analysis demo",
                                    {
                                        "video_asset_ref": "placeholder-log-analysis",
                                        "completion_threshold": 0.9,
                                        "max_credited_rate": 1.0,
                                    },
                                ),
                            ],
                        },
                        {
                            "title": "Ticket Triage",
                            "activities": [
                                (
                                    Activity.ActivityType.WORKSHOP,
                                    "Ticket triage exercise",
                                    {},
                                ),
                            ],
                        },
                    ],
                },
            ],
        },
        {
            "title": "Customer Communication",
            "topics": [
                {
                    "title": "Written Communication",
                    "subtopics": [
                        {
                            "title": "Email Etiquette",
                            "activities": [
                                (
                                    Activity.ActivityType.READING,
                                    "Email etiquette guide",
                                    {
                                        "source_url": "https://docs.hevo.example/email-etiquette",
                                        "estimated_read_minutes": 10,
                                    },
                                ),
                            ],
                        },
                        {
                            "title": "Ticket Responses",
                            "activities": [
                                (
                                    Activity.ActivityType.MANUAL_SIM,
                                    "Ticket response rating",
                                    {},
                                ),
                            ],
                        },
                    ],
                },
                {
                    "title": "Live Interaction",
                    "subtopics": [
                        {
                            "title": "Chat Simulation",
                            "activities": [
                                (
                                    Activity.ActivityType.BOT_SIM,
                                    "Bot chat simulation",
                                    {},
                                ),
                            ],
                        },
                        {
                            "title": "Escalation Handling",
                            "activities": [
                                (
                                    Activity.ActivityType.READING,
                                    "Escalation handling guide",
                                    {
                                        "source_url": "https://docs.hevo.example/escalation",
                                        "estimated_read_minutes": 12,
                                    },
                                ),
                            ],
                        },
                    ],
                },
            ],
        },
    ],
}


def _slug(text: str) -> str:
    return text.lower().replace(" ", "-").replace("&", "and").replace("/", "-")


class Command(BaseCommand):
    help = "Seed a placeholder CX Onboarding course (PLACEHOLDER DATA). Each run adds a new Course."

    @transaction.atomic
    def handle(self, *args, **options):
        base_slug = _slug(TREE["title"]) + "-placeholder"
        slug, n = base_slug, 2
        while Course.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{n}"
            n += 1
        course = Course.objects.create(slug=slug)
        course_version = CourseVersion.objects.create(course=course, version=1)

        root = ContentNode.objects.create(
            course_version=course_version,
            parent=None,
            kind=ContentNode.Kind.COURSE,
            title=TREE["title"] + PLACEHOLDER_TAG,
            slug=_slug(TREE["title"]),
            order=0,
        )
        course_version.root_node = root
        course_version.save(update_fields=["root_node"])

        for seg_order, segment in enumerate(TREE["segments"]):
            seg_node = ContentNode.objects.create(
                course_version=course_version,
                parent=root,
                kind=ContentNode.Kind.SEGMENT,
                title=segment["title"] + PLACEHOLDER_TAG,
                slug=_slug(segment["title"]),
                order=seg_order,
            )
            for topic_order, topic in enumerate(segment["topics"]):
                topic_node = ContentNode.objects.create(
                    course_version=course_version,
                    parent=seg_node,
                    kind=ContentNode.Kind.TOPIC,
                    title=topic["title"] + PLACEHOLDER_TAG,
                    slug=_slug(topic["title"]),
                    order=topic_order,
                )
                for sub_order, subtopic in enumerate(topic["subtopics"]):
                    sub_node = ContentNode.objects.create(
                        course_version=course_version,
                        parent=topic_node,
                        kind=ContentNode.Kind.SUBTOPIC,
                        title=subtopic["title"] + PLACEHOLDER_TAG,
                        slug=_slug(subtopic["title"]),
                        order=sub_order,
                    )
                    for act_order, (activity_type, title, config) in enumerate(
                        subtopic["activities"]
                    ):
                        Activity.objects.create(
                            content_node=sub_node,
                            activity_type=activity_type,
                            title=title,
                            config=config,
                            order=act_order,
                        )

        node_count = ContentNode.objects.filter(course_version=course_version).count()
        activity_count = Activity.objects.filter(
            content_node__course_version=course_version
        ).count()
        self.stdout.write(
            self.style.WARNING(
                f"PLACEHOLDER course tree seeded: CourseVersion v{course_version.version}, "
                f"{node_count} nodes, {activity_count} activities. "
                "Replace with real data once the reference spreadsheets are available."
            )
        )
