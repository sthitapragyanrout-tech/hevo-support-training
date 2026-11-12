"""What is worth telling people, to whom, and how it is worded.

Every function here is called from the service that makes the change (inside its transaction), so
the message exists only if the change does. They never raise: `services.notify` swallows its own
failures. Models are imported lazily where needed so this module can be imported from the services
it is called from without a cycle.

Wording rules: plain, written for the person reading it, with the next step when there is one.
A learner is never given another learner's name, and nothing here ever carries a reference answer,
an answer key or a rater's private note.
"""

from __future__ import annotations

from typing import Any

from . import services

# Kinds (free text in the table; listed here so they are easy to find and filter by).
ENROLLED = "enrolled"
COURSE_UPDATED = "course_updated"
MODULES_CHANGED = "modules_changed"
QUIZ_MARKED = "quiz_marked"
SIM_RATED = "sim_rated"
WORK_WAITING = "work_waiting"
WORK_ASSIGNED = "work_assigned"
DUE_SOON = "due_soon"
OVERDUE = "overdue"
REVIEW_OVERDUE = "review_overdue"
REVIEW_ESCALATED = "review_escalated"
OVERDUE_DIGEST = "overdue_digest"


# ------------------------------------------------------------------------ small helpers


def person(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email or user.username


def course_title(version) -> str:
    return version.root_node.title if version.root_node else version.course.slug


def when(moment) -> str:
    """A short date for a message ("14 Nov")."""
    return f"{moment.day} {moment.strftime('%b')}" if moment else ""


def _lesson_link(activity) -> str:
    """The learner's page for the lesson an activity sits in (or its course)."""
    from apps.progress import services as progress

    version = activity.content_node.course_version
    lesson = progress._lesson_of(activity)
    base = f"/courses/{version.course_id}"
    return f"{base}/lessons/{lesson.pk}" if lesson is not None else base


def _raters(exclude=None):
    """Everyone who may mark or rate work, for work that is open to the whole pool."""
    from apps.manual_sim import eligibility

    people = eligibility.raters()
    return people.exclude(pk=exclude.pk) if exclude is not None else people


def managers():
    """Trainers and admins who manage reviews (they can see and act on everything)."""
    from apps.manual_sim import eligibility

    return eligibility.managers()


# ------------------------------------------------------------------------ learner: courses


def enrolled(enrollment, *, again: bool) -> None:
    title = course_title(enrollment.version)
    services.notify(
        enrollment.user,
        ENROLLED,
        f"You’re enrolled on {title}" + (" again" if again else ""),
        "Open it whenever you’re ready; your lessons and progress are on the course page.",
        f"/courses/{enrollment.course_id}",
        f"enroll:{enrollment.pk}:{enrollment.enrolled_at.isoformat()}",
    )


def moved(enrollment, move) -> None:
    title = course_title(move.to_version)
    services.notify(
        enrollment.user,
        COURSE_UPDATED,
        f"{title} has been updated",
        f"You’re now on version {move.to_version.version}. Anything you had finished that is "
        "unchanged was kept.",
        f"/courses/{enrollment.course_id}",
        f"move:{move.pk}",
    )


def modules_changed(enrollment, enabled: int, total: int) -> None:
    services.notify(
        enrollment.user,
        MODULES_CHANGED,
        f"Your modules for {course_title(enrollment.version)} changed",
        f"You now have {enabled} of {total} modules. What you did in any module that is off is "
        "kept and comes back if it is switched on again.",
        f"/courses/{enrollment.course_id}",
    )


# ------------------------------------------------------------------------ learner: marked


def quiz_marked(review, *, passed: bool, score: float) -> None:
    activity = review.activity
    result = "passed" if passed else "not passed"
    services.notify(
        review.user,
        QUIZ_MARKED,
        f"Your written answers in “{activity.title}” were marked",
        f"Result: {result} ({round(score * 100)}%). Open the quiz to see your marks and feedback.",
        _lesson_link(activity),
        f"quizrate:{review.pk}",
    )


def sim_rated(submission, *, passed: bool, revise_by: Any = None) -> None:
    activity = submission.case.activity
    if passed:
        title, body = f"Your work on “{activity.title}” passed", "Open it to read the feedback."
    else:
        by = f" by {when(revise_by)}" if revise_by else ""
        title = f"Changes requested on “{activity.title}”"
        body = f"Read the feedback and hand in a revised answer{by}."
    services.notify(
        submission.case.user,
        SIM_RATED,
        title,
        body,
        _lesson_link(activity),
        f"simrate:{submission.pk}",
    )


# ------------------------------------------------------------------------ mentors: waiting


def _recipients(item) -> list:
    """Who is told about work: the one person it is routed to, else every eligible rater."""
    mentor = item.assigned_mentor
    if mentor is not None:
        return [mentor]
    return list(_raters(exclude=item.user if hasattr(item, "user") else item.case.user))


def work_waiting_sim(submission, *, key_suffix: str = "") -> None:
    learner = submission.case.user
    activity = submission.case.activity
    services.notify_many(
        _recipients(submission),
        WORK_WAITING,
        f"New work to review: {activity.title}",
        f"{person(learner)} handed in revision {submission.revision}. "
        f"Review due {when(submission.review_due_at)}.",
        f"/admin/ratings/{submission.pk}",
        f"waiting:sim:{submission.pk}{key_suffix}",
    )


def work_waiting_quiz(review, *, key_suffix: str = "") -> None:
    services.notify_many(
        _recipients(review),
        WORK_WAITING,
        f"Written quiz answers to mark: {review.activity.title}",
        f"{person(review.user)} submitted attempt {review.attempt_no}. "
        f"Review due {when(review.review_due_at)}.",
        f"/admin/ratings/quiz/{review.pk}",
        f"waiting:quiz:{review.pk}{key_suffix}",
    )


def work_assigned(mentor, count: int) -> None:
    """A mentor is given a learner, and their waiting work comes with them."""
    services.notify(
        mentor,
        WORK_ASSIGNED,
        f"{count} review{'s' if count != 1 else ''} moved to you",
        "A learner was assigned to you and their waiting work is now yours.",
        "/admin/ratings",
    )


def work_reassigned(kind: str, item) -> None:
    """A manager moved one review. People told about it before are cleared; the new owner (or the
    pool) is told again, under a key that includes the time so it is never swallowed as a repeat."""
    from django.utils import timezone

    services.resolve(f"waiting:{kind}:{item.pk}:")
    suffix = f":r{int(timezone.now().timestamp())}"
    if kind == "sim":
        work_waiting_sim(item, key_suffix=suffix)
    else:
        work_waiting_quiz(item, key_suffix=suffix)


def work_done(kind: str, item_id: int) -> None:
    """The review was rated, withdrawn or closed: nobody needs to be reminded about it now."""
    services.resolve(f"waiting:{kind}:{item_id}:")
    services.resolve(f"review-overdue:{kind}:{item_id}:")
    services.resolve(f"review-escalated:{kind}:{item_id}:")
