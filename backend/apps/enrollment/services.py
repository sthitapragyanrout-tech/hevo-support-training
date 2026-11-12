"""Putting people on courses. Every rule about enrolling lives here; the Console only
translates HTTP.

* **What you are put on:** the course's latest *published* version, pinned for good (until a
  trainer moves you). A course with no published version, or an archived one, cannot be enrolled
  on.
* **One row per learner and course.** Enrolling again is harmless; enrolling someone who was
  withdrawn brings the same row back (history intact) on the then-latest version.
* **Mentors** are per learner per course and are written only through
  `manual_sim.assignments`; a mentor that cannot be assigned stops the enrollment, so nobody is
  left half-enrolled.
* **Withdrawing** hides the course and returns the learner's unrated work to the pool. Nothing
  they did is deleted.
* **Bulk enrolling** previews first and applies through the very same code: `bulk` with
  `apply=False` only reads; with `apply=True` it does exactly what the preview listed.

Callers audit (they know the request); these functions return what happened.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from apps.catalog.models import Course, CourseVersion
from apps.manual_sim import assignments
from apps.manual_sim.errors import SimError
from apps.notifications import events

from . import modules as modules_
from .errors import Conflict, EnrollmentError, NotFound
from .models import Enrollment, Program, ProgramCourse

User = get_user_model()

MAX_BULK_ROWS = 500
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

# Outcomes of one enrollment attempt.
ENROLLED = "enrolled"
REACTIVATED = "reactivated"
ALREADY = "already"


# ------------------------------------------------------------------------ helpers


def enrollable_version(course: Course) -> CourseVersion:
    """The version a new enrollment is pinned to, or a plain refusal."""
    if course.archived_at is not None:
        raise Conflict("That course is archived, so no one can be enrolled on it.")
    version = (
        course.versions.filter(state=CourseVersion.State.PUBLISHED, root_node__isnull=False)
        .order_by("-version")
        .first()
    )
    if version is None:
        raise Conflict(
            "That course has no published version yet, so there is nothing to enroll on."
        )
    return version


def _check_mentor(learner, mentor) -> None:
    if mentor is not None and not assignments.is_eligible_mentor(mentor, learner):
        raise EnrollmentError(
            "That person can’t be this learner’s mentor. A mentor must be active, "
            "be allowed to rate simulations, and not be the learner."
        )


def mentor_of(enrollment: Enrollment):
    return assignments.mentor_for(enrollment.user, enrollment.course)


def _name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email or user.username


# ----------------------------------------------------------------------- enrolling


@transaction.atomic
def enroll(
    user,
    course: Course,
    *,
    mentor=None,
    program: Program | None = None,
    modules: Iterable[int] | None = None,
    by=None,
    source: str = Enrollment.Source.MANUAL,
    now=None,
) -> tuple[Enrollment, str]:
    """Put `user` on `course`. Returns (the enrollment, ENROLLED | REACTIVATED | ALREADY).

    `modules` are the module ids to give them (None = every module). It sets a new or
    re-activated enrollment; for someone already enrolled it is ignored (use `set_modules`)."""
    if not user.is_active:
        raise EnrollmentError(f"{_name(user)}’s account is deactivated.")
    now = now or timezone.now()
    version = enrollable_version(course)
    _check_mentor(user, mentor)
    off = modules_.excluded_ids(version, modules)

    row = Enrollment.objects.select_for_update().filter(user=user, course=course).first()
    if row is None:
        try:
            with transaction.atomic():
                row = Enrollment.objects.create(
                    user=user,
                    course=course,
                    version=version,
                    program=program,
                    state=Enrollment.State.ACTIVE,
                    source=source,
                    enrolled_at=now,
                    enrolled_by=by,
                )
                modules_.write_exclusions(row, off)
            outcome = ENROLLED
        except IntegrityError:  # someone enrolled them a moment ago: fine, it is the same fact
            row = Enrollment.objects.select_for_update().get(user=user, course=course)
            outcome = ALREADY
    elif row.state == Enrollment.State.WITHDRAWN:
        row.state = Enrollment.State.ACTIVE
        row.version = version
        row.program = program or row.program
        row.source = source
        row.enrolled_at = now
        row.enrolled_by = by
        row.withdrawn_at = None
        row.withdrawn_by = None
        row.withdrawn_reason = ""
        row.save()
        # The old selection named modules of the old pin; start from what was asked for now.
        modules_.write_exclusions(row, off)
        outcome = REACTIVATED
    else:
        outcome = ALREADY
        if program is not None and row.program_id is None:
            row.program = program
            row.save(update_fields=["program"])

    if outcome in (ENROLLED, REACTIVATED):
        events.enrolled(row, again=outcome == REACTIVATED)
    if mentor is not None:
        assignments.assign_mentor(user, course, mentor, by=by)
    return row, outcome


@transaction.atomic
def withdraw(enrollment: Enrollment, reason: str, *, by=None, now=None) -> Enrollment:
    """Take the learner off the course. Their progress stays; the course stops appearing."""
    row = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
    if row.state == Enrollment.State.WITHDRAWN:
        raise Conflict("They are already withdrawn from this course.")
    reason = (reason or "").strip()
    if len(reason) > 300:
        raise EnrollmentError("Keep the reason to 300 characters or fewer.")
    row.state = Enrollment.State.WITHDRAWN
    row.withdrawn_at = now or timezone.now()
    row.withdrawn_by = by
    row.withdrawn_reason = reason
    row.save()
    assignments.unassign_mentor(row.user, row.course, by=by)
    _close_open_tickets(row)
    return row


def _close_open_tickets(row: Enrollment) -> None:
    """A practice ticket still open on a course they have left is closed (uncounted); one already
    being scored finishes on its own."""
    from apps.bot_sim.models import SimSession

    SimSession.objects.filter(
        user=row.user,
        preview=False,
        state=SimSession.State.OPEN,
        activity__content_node__course_version__course=row.course,
    ).update(state=SimSession.State.ABANDONED, abandon_reason="withdrawn")


@transaction.atomic
def change_mentor(enrollment: Enrollment, mentor, *, by=None) -> Enrollment:
    """Set (or, with None, clear) the learner's mentor for this course."""
    row = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
    if row.state != Enrollment.State.ACTIVE:
        raise Conflict("They are withdrawn from this course; re-enroll them first.")
    if mentor is None:
        assignments.unassign_mentor(row.user, row.course, by=by)
    else:
        _check_mentor(row.user, mentor)
        assignments.assign_mentor(row.user, row.course, mentor, by=by)
    return row


# ------------------------------------------------------------------------ programs


@dataclass
class CourseResult:
    course: Course
    outcome: str  # ENROLLED | REACTIVATED | ALREADY | "skipped"
    detail: str = ""


def program_courses(program: Program) -> list[Course]:
    return [i.course for i in program.items.select_related("course").order_by("order", "id")]


def enroll_program(user, program: Program, *, mentor=None, by=None, now=None) -> list[CourseResult]:
    """Enroll `user` on every course in the program that can be enrolled on. A course that
    cannot (no published version, archived) is reported, not an error: the rest go ahead."""
    if program.archived_at is not None:
        raise Conflict("That program is archived.")
    out: list[CourseResult] = []
    for course in program_courses(program):
        try:
            _, outcome = enroll(
                user,
                course,
                mentor=mentor,
                program=program,
                by=by,
                source=Enrollment.Source.PROGRAM,
                now=now,
            )
            out.append(CourseResult(course, outcome))
        except Conflict as exc:
            out.append(CourseResult(course, "skipped", exc.message))
    return out


# ---------------------------------------------------------------------------- bulk


@dataclass
class Row:
    line: int
    raw: str
    email: str = ""
    mentor_email: str = ""
    status: str = ""  # see STATUSES
    detail: str = ""
    user: Any = None
    mentor: Any = None
    courses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        return self.status in ("will_enroll", "will_reactivate")


# What the preview can say about a row, in plain words.
STATUSES = {
    "failed": "Could not be enrolled",
    "will_enroll": "Will be enrolled",
    "will_reactivate": "Will be re-enrolled",
    "already_enrolled": "Already enrolled",
    "unknown_email": "No account with this email",
    "inactive_user": "Account is deactivated",
    "not_a_learner": "Not a learner",
    "invalid_mentor": "Mentor can’t be used",
    "duplicate": "Listed more than once",
    "bad_email": "Not an email address",
    "nothing_to_enroll": "Nothing to enroll on",
}


def parse_rows(text: str) -> list[Row]:
    """`email[,mentor_email]` per line (comma, semicolon, tab or space separated; a header row
    and blank lines are skipped)."""
    if not isinstance(text, str):
        raise EnrollmentError("Paste a list of email addresses, one per line.")
    rows: list[Row] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        cells = [c.strip("\"'") for c in re.split(r"[,;\t ]+", stripped) if c.strip("\"'")]
        if not cells:
            continue
        if not rows and cells[0].lower() in ("email", "email address", "e-mail"):
            continue  # a header row
        rows.append(
            Row(
                line=number,
                raw=stripped,
                email=cells[0].lower(),
                mentor_email=cells[1].lower() if len(cells) > 1 else "",
            )
        )
        if len(rows) > MAX_BULK_ROWS:
            raise EnrollmentError(
                f"That is more than {MAX_BULK_ROWS} rows. Split the list and do it in parts."
            )
    if not rows:
        raise EnrollmentError("The list is empty. Paste one email address per line.")
    return rows


def _learner_ids(users) -> set[int]:
    from apps.accounts.models import RoleAssignment

    return set(
        RoleAssignment.objects.filter(user__in=users, role__name="learner").values_list(
            "user_id", flat=True
        )
    )


def bulk(
    text: str,
    *,
    course: Course | None = None,
    program: Program | None = None,
    default_mentor=None,
    modules: Iterable[int] | None = None,
    by=None,
    apply: bool = False,
    now=None,
) -> list[Row]:
    """Read the list and say what would happen to each row; with `apply`, do it.

    Exactly one of `course` / `program` is the target. Unknown emails are reported, never
    created (making an account is a separate job). Each row is its own transaction, so one bad
    row cannot undo the others. `modules` is one choice of modules for everyone newly enrolled
    in this run, so it only makes sense for a single course."""
    if (course is None) == (program is None):
        raise EnrollmentError("Choose a course or a program to enroll them on.")
    if modules is not None:
        modules = list(modules)
        if program is not None:
            raise EnrollmentError(
                "Choosing modules works for one course at a time. Enroll the program with "
                "every module, then trim individual learners."
            )
        try:  # a bad choice stops the whole run, before anyone is touched
            modules_.excluded_ids(enrollable_version(course), modules)  # type: ignore[arg-type]
        except Conflict:
            pass  # no published version: every row will say so itself
    targets = [course] if course is not None else program_courses(program)  # type: ignore[arg-type]
    if not targets:
        raise Conflict("That program has no courses yet.")
    rows = parse_rows(text)

    emails = {r.email for r in rows} | {r.mentor_email for r in rows if r.mentor_email}
    by_email = {
        u.email.lower(): u
        for u in User.objects.annotate(lowered=Lower("email")).filter(lowered__in=emails)
    }
    learner_ids = _learner_ids(list(by_email.values()))

    seen: set[str] = set()
    for row in rows:
        _judge(row, by_email, learner_ids, seen, targets, default_mentor, program)
        if apply and row.actionable:
            _apply_row(row, targets, program, by, now, modules)
    return rows


def _judge(row, by_email, learner_ids, seen, targets, default_mentor, program) -> None:
    if not _EMAIL.match(row.email):
        row.status, row.detail = "bad_email", f"“{row.email}” doesn’t look like an email address."
        return
    if row.email in seen:
        row.status, row.detail = "duplicate", "This address is already listed above."
        return
    seen.add(row.email)
    user = by_email.get(row.email)
    if user is None:
        row.status = "unknown_email"
        row.detail = "Create the account first (People → Users), then enroll them."
        return
    row.user = user
    if not user.is_active:
        row.status, row.detail = "inactive_user", "Reactivate the account first."
        return
    if user.pk not in learner_ids:
        row.status = "not_a_learner"
        row.detail = "They don’t hold the Learner role. Add the role, or enroll them one at a time."
        return
    if row.mentor_email:
        mentor = by_email.get(row.mentor_email)
        row.mentor = mentor
        if mentor is None or not assignments.is_eligible_mentor(mentor, user):
            row.status = "invalid_mentor"
            row.detail = f"{row.mentor_email} isn’t an active mentor who can rate simulations."
            return
    elif default_mentor is not None:
        row.mentor = default_mentor
        if not assignments.is_eligible_mentor(default_mentor, user):
            row.status = "invalid_mentor"
            row.detail = "The chosen mentor can’t be this learner’s mentor."
            return

    existing = {e.course_id: e for e in Enrollment.objects.filter(user=user, course__in=targets)}
    for course in targets:
        found = existing.get(course.pk)
        try:
            enrollable_version(course)
            state = (
                "already"
                if found is not None and found.state == Enrollment.State.ACTIVE
                else "reactivate"
                if found is not None
                else "enroll"
            )
            detail = ""
        except Conflict as exc:
            state, detail = "skipped", exc.message
        row.courses.append({"id": course.pk, "state": state, "detail": detail})

    states = {c["state"] for c in row.courses}
    if "enroll" in states:
        row.status = "will_enroll"
    elif "reactivate" in states:
        row.status = "will_reactivate"
    elif "already" in states:
        row.status = "already_enrolled"
    else:
        row.status, row.detail = "nothing_to_enroll", row.courses[0]["detail"]


def _apply_row(row: Row, targets, program, by, now, modules=None) -> None:
    try:
        with transaction.atomic():
            for course in targets:
                _, outcome = enroll(
                    row.user,
                    course,
                    mentor=row.mentor,
                    program=program,
                    modules=modules,
                    by=by,
                    source=Enrollment.Source.PROGRAM if program else Enrollment.Source.IMPORT,
                    now=now,
                )
                for entry in row.courses:
                    if entry["id"] == course.pk and entry["state"] in ("enroll", "reactivate"):
                        entry["state"] = "done"
                        entry["outcome"] = outcome
    except (EnrollmentError, SimError) as exc:
        row.status = "failed"
        row.detail = getattr(exc, "message", str(exc))
        for entry in row.courses:
            if entry["state"] == "done":
                entry["state"] = "failed"


def summarise(rows: list[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row.status] = out.get(row.status, 0) + 1
    return out


# ----------------------------------------------------------------------- programs


def _validate_program_fields(name, starts_on, ends_on):
    name = (name or "").strip()
    if not name:
        raise EnrollmentError("Give the program a name.")
    if len(name) > 200:
        raise EnrollmentError("Program names can be at most 200 characters.")
    if starts_on and ends_on and ends_on < starts_on:
        raise EnrollmentError("A program can’t end before it starts.")
    return name


@transaction.atomic
def save_program(
    program: Program | None,
    *,
    name,
    description="",
    starts_on=None,
    ends_on=None,
    courses: list[tuple[int, bool]] | None = None,
    by=None,
) -> Program:
    """Create or update a program; `courses` is the whole ordered list as (course id, required)."""
    name = _validate_program_fields(name, starts_on, ends_on)
    clash = Program.objects.filter(name__iexact=name, archived_at__isnull=True)
    if program is not None:
        clash = clash.exclude(pk=program.pk)
    if clash.exists():
        raise Conflict("There is already a program with that name.")
    if program is None:
        program = Program(created_by=by)
    program.name = name
    program.description = (description or "").strip()
    program.starts_on = starts_on
    program.ends_on = ends_on
    program.save()
    if courses is not None:
        ids = [cid for cid, _ in courses]
        if len(set(ids)) != len(ids):
            raise EnrollmentError("A course can only appear once in a program.")
        found = {c.pk: c for c in Course.objects.filter(pk__in=ids)}
        if set(found) != set(ids):
            raise NotFound("One of those courses doesn’t exist.")
        if any(c.archived_at is not None for c in found.values()):
            raise Conflict("An archived course can’t be in a program.")
        program.items.all().delete()
        ProgramCourse.objects.bulk_create(
            ProgramCourse(program=program, course=found[cid], order=i, is_required=required)
            for i, (cid, required) in enumerate(courses)
        )
    return program


@transaction.atomic
def archive_program(program: Program, *, now=None) -> Program:
    if program.archived_at is not None:
        raise Conflict("That program is already archived.")
    program.archived_at = now or timezone.now()
    program.save(update_fields=["archived_at"])
    return program


@transaction.atomic
def restore_program(program: Program) -> Program:
    if program.archived_at is None:
        raise Conflict("That program isn’t archived.")
    if Program.objects.filter(name__iexact=program.name, archived_at__isnull=True).exists():
        raise Conflict("Another program has taken this name; rename that one first.")
    program.archived_at = None
    program.save(update_fields=["archived_at"])
    return program


def enroll_missing(program: Program, *, by=None, now=None) -> dict[str, int]:
    """Bring everyone already in the program up to date with it: enroll them on any of its
    courses added since (and not on one they have withdrawn from). Returns counts."""
    if program.archived_at is not None:
        raise Conflict("That program is archived.")
    members = list(User.objects.filter(enrollments__program=program, is_active=True).distinct())
    added = skipped = 0
    for user in members:
        for course in program_courses(program):
            have = Enrollment.objects.filter(user=user, course=course).first()
            if have is not None:
                continue  # already on it, or withdrawn on purpose
            try:
                enroll(
                    user,
                    course,
                    program=program,
                    by=by,
                    source=Enrollment.Source.PROGRAM,
                    now=now,
                )
                added += 1
            except Conflict:
                skipped += 1
    return {"people": len(members), "enrolled": added, "skipped": skipped}
