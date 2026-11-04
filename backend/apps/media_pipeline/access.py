"""Who may do what with a media asset — one module, so the rules read in one place.

Managing (poll, retry, attach):
  an author, for what they uploaded; an administrator (anyone who may publish),
  for everything.

Viewing (stream the video or its poster):
  anonymous           refused (403, like the rest of the API)
  an author           what they uploaded, or what any draft / in-review course
                      uses (so the Studio preview works); an administrator, all
  everyone else       only a **ready** video that a **published, not archived**
                      course uses, **and** whose lesson is open to them under the
                      course's order. If the course goes in order and the lesson
                      is still locked, the answer is the same 409 the progress
                      API gives.
  anything else       404 — the same answer as "no such video", so nobody learns
                      which ids exist.

The check runs on *every* request, range requests included, so archiving or
unpublishing a course cuts off streaming straight away.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet

from apps.accounts.rbac import can
from apps.catalog.models import Activity, CourseVersion
from apps.progress import services as progress

from .models import MediaAsset

AUTHOR = "catalog.author_content"
ADMIN = "catalog.publish_courseversion"


def can_manage(user, asset: MediaAsset) -> bool:
    """Poll, retry or attach this asset."""
    if not can(user, AUTHOR):
        return False
    return asset.uploaded_by_id == user.pk or can(user, ADMIN)


def uses_of(asset_id: int) -> QuerySet[Activity]:
    """Every video activity (in any version of any course) that plays this asset."""
    return Activity.objects.filter(activity_type="video", config__media_asset=asset_id)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    # Set when refused because an earlier lesson isn't finished.
    locked: progress.LessonLocked | None = None


ALLOW = Verdict(True)
DENY = Verdict(False)


def can_view(user, asset: MediaAsset) -> Verdict:
    """May `user` stream this asset right now? (The caller handles anonymous.)"""
    uses = list(uses_of(asset.pk).select_related("content_node__course_version__course"))

    if can(user, AUTHOR):
        if asset.uploaded_by_id == user.pk or can(user, ADMIN):
            return ALLOW
        if any(a.content_node.course_version.state in _OPEN for a in uses):
            return ALLOW

    # The learner rule (authors fall through to it for published courses too).
    if asset.status != MediaAsset.Status.READY:
        return DENY
    published = [a for a in uses if _published(a.content_node.course_version)]
    if not published:
        return DENY
    first_lock: progress.LessonLocked | None = None
    for activity in published:
        lock = progress.lock_of(user, progress.lesson_of(activity))
        if lock is None:
            return ALLOW
        first_lock = first_lock or lock
    return Verdict(False, locked=first_lock)


_OPEN = {s.value for s in CourseVersion.OPEN_STATES}


def _published(version: CourseVersion) -> bool:
    return version.state == CourseVersion.State.PUBLISHED and version.course.archived_at is None
