"""Shared builders for the mentor-rated simulation tests."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import Role
from apps.catalog import services as catalog
from apps.catalog.models import Activity

# "Now", to the hour. A fixed date would drift into the past and silently turn work that
# is meant to be fresh into work that is overdue (the queue reads the real clock).
T0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def at(**delta) -> datetime:
    return T0 + timedelta(**delta)


CRITERIA = [
    {
        "key": "diagnosis",
        "label": "Diagnosis",
        "description": "Found the cause",
        "guidance": "RATER-ONLY: 5 = exact",
    },
    {
        "key": "tone",
        "label": "Tone",
        "description": "Kind and clear",
        "guidance": "RATER-ONLY: 5 = warm",
    },
]


def good_config(**over) -> dict:
    return {
        "scenario": "A customer's pipeline stopped syncing overnight.",
        "handin": "Your reply to the customer.",
        "criteria": CRITERIA,
        "pass_threshold": 0.7,
        "min_each": 0,
        "allow_files": True,
        "due_days": 7,
        "revision_days": 3,
        **over,
    }


PASS = {"diagnosis": 5, "tone": 4}
FAIL = {"diagnosis": 2, "tone": 3}


def rated_course(
    make_role_user,
    *,
    order: str = "free",
    config: dict | None = None,
    max_attempts: int = 0,
    title: str = "Rated course",
    publish: bool = True,
    required: bool = True,
):
    """A course whose second lesson holds a mentor-rated simulation (and whose first lesson
    holds a required reading, so a course that goes in order locks the simulation). A third
    lesson lets tests see what the simulation holds up."""
    author = make_role_user(Role.Name.TRAINER, username=f"a-{title}", email=f"a-{title}@e.com")
    admin = make_role_user(Role.Name.ADMIN, username=f"adm-{title}", email=f"adm-{title}@e.com")
    course = catalog.create_course(title=title, user=author)
    version = catalog.open_version(course)
    assert version is not None and version.root_node is not None
    module = catalog.add_node(version.root_node, title="Module")
    first = catalog.add_node(module, title="First")
    Activity.objects.create(
        content_node=first,
        activity_type="reading",
        title="Read",
        config={"source_url": "https://x.io"},
    )
    second = catalog.add_node(module, title="Second")
    activity = Activity.objects.create(
        content_node=second,
        activity_type="manual_sim",
        title="Customer reply",
        config=good_config(**(config or {})),
        max_attempts=max_attempts,
        is_required=required,
    )
    third = catalog.add_node(module, title="Third")
    Activity.objects.create(
        content_node=third,
        activity_type="reading",
        title="Later",
        config={"source_url": "https://y.io"},
    )
    catalog.set_learning_order(version, order)
    if publish:
        version.publish(admin)
    return {
        "course": course,
        "version": version,
        "first": first,
        "second": second,
        "third": third,
        "activity": activity,
        "author": author,
        "admin": admin,
    }


def people(make_role_user):
    return {
        "learner": make_role_user(Role.Name.LEARNER, username="lea", email="lea@e.com"),
        "other": make_role_user(Role.Name.LEARNER, username="oth", email="oth@e.com"),
        "mentor": make_role_user(Role.Name.MENTOR, username="mia", email="mia@e.com"),
        "mentor2": make_role_user(Role.Name.MENTOR, username="max", email="max@e.com"),
        "trainer": make_role_user(Role.Name.TRAINER, username="tom", email="tom@e.com"),
        "root": make_role_user(Role.Name.ADMIN, username="ada", email="ada@e.com"),
    }


# ----------------------------------------------------------------------- attachments


def png(name: str = "shot.png", size=(8, 8)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def jpeg(name: str = "shot.jpg", size=(8, 8)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 200, 30)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def webp(name: str = "shot.webp", size=(8, 8)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 30, 200)).save(buffer, "WEBP")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/webp")


def pdf(name: str = "notes.pdf", body: bytes = b"hello") -> SimpleUploadedFile:
    data = b"%PDF-1.4\n1 0 obj<<>>endobj\n" + body + b"\ntrailer<<>>\n%%EOF\n"
    return SimpleUploadedFile(name, data, content_type="application/pdf")
