# Mentor-rated simulations (Module 6)

A learner is given a realistic task, hands work in, a mentor rates it against a rubric, and the
learner revises from the feedback until it passes. It is the one activity where a **person**, not
code, is the judge — so time (on both sides) and "stuck" cases are first-class. Built on the
existing progress engine; no video, no bot.

## The flow

1. **Open.** The learner opens the activity: the deadline starts (once). Reading it never starts it.
2. **Hand in.** One request carries the answer (≤ 10 000 characters), up to 5 links (http/https
   only) and up to 5 files. One piece of work may wait at a time. Late work is accepted and marked
   *late*.
3. **Review.** It goes to the learner's mentor for that course, else to the shared pool. A mentor
   rates every criterion 1–5, may add feedback per criterion, and must add an overall comment.
   A rating is final.
4. **Revise.** If the average is under the pass mark (or any criterion is under the optional
   minimum), changes are requested and a revision window starts. The learner hands in a *revision*;
   every earlier revision, its files and its rating are kept. There is **no attempt limit**: the
   deadlines bound the work, and after three unsuccessful reviews the case is flagged for a trainer.
5. **Pass.** A passing rating completes the activity.

## Scoring (same contract as practice tickets)

Each criterion 1–5. Overall = the mean on the 1–5 scale, **rounded once, half-up, to two
decimals** (`simbot_engine.outcome`); scaled = overall / 5; passed ⇔ overall ≥ pass mark × 5
(compared exactly) and, if `min_each` is set, no criterion below it. Shown as "3.5 / 5", **never a
percentage**. Equal weights in V1.

## Two clocks, never mixed

| Clock | Where | Starts | Overdue means |
|---|---|---|---|
| Learner's deadline | `SimCase.due_at` | first opening (`due_days`), then when changes are requested (`revision_days`); a trainer/admin can extend | nothing is waiting or passed and now is past it |
| Mentor's review target | `SimSubmission.review_due_at` | when work is handed in; **independent of lateness** | still waiting past it |

Overdue is **computed from timestamps when read, never stored**. A review overdue by more than the
grace (`MANUAL_SIM_ESCALATION_GRACE_HOURS`, 24 h) becomes open to any eligible rater ("escalated").

## What affects a course (progression)

A lesson holds the next one (in an ordered course) until every **required** activity is *finished*
(`completed` or `exhausted`). Optional lessons and courses with no order never gate.

A simulation has one setting, **What holds the next lesson** (`holds_next`, authored in Studio):

* **`submit` (default): handing the work in opens the next lesson.** A slow review never keeps a learner
  from moving on. The lesson is marked complete as usual, but as *provisional*
  (`LessonCompletion.provisional`): it opens what follows, and it is **not counted as complete anywhere**
  (the learner's progress, the Console's lesson counts, the learner detail) until the rating passes, or a
  trainer/admin waives or closes the case. The server reports such lessons as `awaiting_review_lessons`,
  separately from `completed_lessons`.
* **`pass`**: the strict rule — the next lesson stays locked until the rating passes.

| Situation | `submit` (default) | `pass` |
|---|---|---|
| Not handed in, before the deadline | blocks | blocks |
| **Overdue, not handed in** | **still blocks** — flagged "Overdue"; nothing automatic | same |
| Handed in, waiting for a mentor (even if the review is overdue) | **opens the next lesson**; lesson provisional; the review is escalated | blocks |
| Changes requested / needs attention | stays open (nothing re-locks); flagged, never auto-failed | blocks |
| Passed | `completed`; the lesson settles (counts as complete) | `completed` |
| **Waived** or **closed** by a trainer/admin | `exhausted` ("finished, not passed"): stops blocking, recorded **which**, never counts as passed |
| Reopened | back to started with a fresh deadline; a lesson finished only because of it is reopened, unless work is already handed in (then it is provisional again) |

Only a trainer or an admin can **extend, waive, close or reopen** (reason required, audited).
Waiving or closing withdraws anything waiting, so a rating can't arrive afterwards.

## Who rates what

Two permissions (Admin → Roles; both in the role matrix):

* `manual_sim.rate_submissions` — **Rate simulations**: Mentor, Trainer, Admin.
* `manual_sim.manage_reviews` — **Manage simulation reviews** (reassign, extend, waive, close,
  reopen, take over a claim, rate any submission): Trainer, Admin. Admins can't drop it.

Nobody can rate their **own** work, whatever their role. The scope check lives in
`apps/manual_sim/access.py` (`rbac.can(user, action, obj)`'s object check is deliberately a no-op),
and every endpoint that touches a submission goes through it.

**Mentors are per learner, per course, and set at course enrolment — never at account creation.**
`apps/manual_sim/assignments.py` is the only code that writes `MentorAssignment` or decides routing
(`assign_mentor`, `unassign_mentor`, `route_for`, `reroute_open`). **The enrolment workflow doesn't
exist yet, so nothing calls them and every submission goes to the shared pool.** There is
deliberately no platform-wide mentor and no temporary assignment screen. When assignments exist, a
mentor who is deactivated or loses the permission is ignored (the work falls to the pool). A
change re-routes the learner's *unrated* work for that course (claim cleared, draft kept); work a
trainer routed by hand, and rated work, stay put.

The queue (Admin → Review → Ratings): **Mine** (routed to you), **Shared pool** (incl. escalated),
and for trainers/admins **All waiting** and **Needs a trainer**. A pool item is *claimed* for two
hours (a lease); a trainer can take it over.

## Files

PNG, JPEG, WebP or PDF, ≤ 10 MB each, ≤ 25 MB per hand-in, ≤ 5 files (all settings). The type is
decided from the file's **bytes** (never the extension or the browser's `Content-Type`); images are
also opened with Pillow (header, pixel cap, integrity); SVG, HTML, zip and Office files are refused.
Stored as `MEDIA_ROOT/attachments/<uuid>.<ext>` — nothing the uploader typed reaches the file
system — and **never re-encoded**. Served only by `GET /api/v1/rated-sims/files/<uuid>/` after an
access check on every request (the author; anyone who may rate that work; trainers/admins; people who
view results), with `nosniff`, `Cache-Control: private`, a sandboxing `Content-Security-Policy`,
images inline and **PDFs always downloaded**. A row's deletion removes its file;
`manage.py purge_orphan_attachments [--dry-run]` sweeps strays.

**Not done:** antivirus scanning; EXIF metadata is not stripped from images.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `MANUAL_SIM_REVIEW_HOURS` | 48 | a mentor's review target (an activity may override it) |
| `MANUAL_SIM_ESCALATION_GRACE_HOURS` | 24 | after the target, an overdue review opens to any rater |
| `MANUAL_SIM_ATTENTION_AFTER` | 3 | unsuccessful reviews before "needs attention" |
| `MANUAL_SIM_EXTEND_MAX_DAYS` | 14 | most a trainer can extend in one go |
| `MANUAL_SIM_CLAIM_MINUTES` | 120 | a claim's lease |
| `MANUAL_SIM_MAX_ANSWER_CHARS` / `_MAX_LINKS` | 10 000 / 5 | |
| `MANUAL_SIM_MAX_FILES` / `_MAX_FILE_MB` / `_MAX_TOTAL_MB` / `_MAX_PIXELS` | 5 / 10 / 25 / 36 000 000 | |

Authors set, per activity (Studio → the activity): scenario, what to hand in, the rubric (label,
what it looks at, **guidance for raters** which learners never see), pass mark (out of 5), an optional
lowest score per criterion, days to hand in, days to revise, review target, and whether files are
allowed. New activities default to 7 days to hand in and 3 to revise (0 = none).

## Operations

* **Roles on an existing database.** The migration `manual_sim.0002` creates the two permissions and
  adds them — additively, once — to the built-in Mentor, Trainer and Admin roles. A later Console
  removal sticks. **Do not re-run `make seed` / `make dev-seed` on a live database to pick them up:**
  `seed_roles` resets the four built-in roles to the code defaults and erases Console edits.
* Nothing needs a scheduler: overdue and escalation are computed when read.
* `nginx` isn't defined in this repo. With `MEDIA_ACCEL_REDIRECT` set, the files are handed off with
  `X-Accel-Redirect: <prefix>/attachments/<uuid>.<ext>`; that internal location must cover
  `attachments/` (unverified, as for video).
* Courses with a mentor-rated simulation can't be **published** until someone can rate (a mentor
  exists), as practice tickets can't be published with no approved scenarios.
* Attempts on a mentor-rated simulation **can't be reset** (it would erase the history); use extend,
  waive, close or reopen.

## Known limits

* **No reminders.** In-app indicators and queues only — no email, Slack or push. A deadline is seen
  only when someone opens the screen.
* **No amendments.** A rating is final; there is no versioned re-rating. A wrong rating is corrected
  by an admin out of band (restricted Django Admin / database), and that is a known gap.
* No second rater or calibration; equal-weight criteria; no competency rollup; calendar hours only
  (no business-hours SLA).
* **Everything is in the shared pool until enrolment assigns mentors,** so every eligible rater can see
  every learner's submission from any course. Scoping the pool by course is a later decision.
* With `submit` a learner can move on before any feedback arrives (that is the point), and a poor first
  hand-in opens the next lesson just the same. Withdrawing afterwards does not lock anything again; the lesson
  stays provisional, so the course still doesn't complete without a pass. There is still no record of a course
  being "complete" (no certificate yet): it means every lesson is settled.
* **Your own work is listed for managers in the All tab** (marked "Your own work", no rate button) so it isn't
  a mystery; Mine and the pool never show it. With a single admin account nobody else can rate it.
* No antivirus scanning; EXIF kept; PDFs download rather than preview; one-server local storage.
* The CSV export gains "Mentor-rated" attempt rows (score out of 5, no percent) but **no deadline,
  overdue or revision columns** — those are on the learner's page in the Console.

## What was verified

* **Backend tests** — 1777 pass on SQLite; the whole suite on Postgres passes except one failure that was
  already there (`test_console_users::TestList::test_search_filter_and_order`, a locale-collation ordering
  difference). The new module has race tests that need real row locks (double hand-in, two raters, claims, rating
  while closing) and run on Postgres only. A mutation check of the key guards (own-work, claims, rating twice, closed
  cases, file sniffing, waive-as-pass, mentors extending, guidance leaking, banker's rounding, attempt reset,
  lateness, the two clocks, the case lock) found every one caught.
* **Frontend tests** — 545 pass; type-check, lint and build are clean.
* **A real-browser run** (throwaway learner, mentor, trainer and admin, deleted afterwards): a learner opened the
  activity, a disguised file was refused with a sentence, a PNG and a PDF were handed in; the mentor found it in the pool,
  saw the image served through the authorised endpoint, rated it "changes requested"; the learner read the feedback,
  revised and handed in again; a trainer extended the deadline, reassigned the submission and passed it; the learner's
  lesson completed and the next lesson unlocked. The phone-width learner screen had no horizontal overflow. In Studio
  three edits made in quick succession all persisted.
* The permission migration was run against the development database (which already had the roles) and a throwaway
  one; the grants landed additively.

**Not verified:** overdue and "escalated" display in a browser (only by tests with an injected clock), waive / close /
reopen in a browser (tests only), a mentor assigned through `assign_mentor` in a browser (tests only — nothing calls it
yet), nginx and the Docker image, a real multipart upload through a production proxy, antivirus, and lazy escalation
over real days.
