# Studio: authoring in the React app

The Studio (`/studio`) is where trainers and admins build courses. Django Admin
stays as the back-office (inspection, emergency fixes, users and roles).

## Concepts

| Author sees | Stored as |
|---|---|
| Course | `Course` (stable identity) → `CourseVersion` (a snapshot) → `ContentNode` tree |
| Module | `ContentNode(kind=segment)` |
| Lesson | `ContentNode(kind=topic)` |
| Section | `ContentNode(kind=subtopic)` — content grouping *inside* a lesson page, not a nav level |
| Activity | `Activity` on a lesson or a section; type + JSON `config` from `apps/activities/registry.py` |

Authors never see versions, ids, kinds or slugs. The API takes *intent*
(`parent`, `title`); the server derives kind, slug, order and version
(`catalog/services.py`).

## Lifecycle

```
Create → Draft ──Submit (trainer)──▶ In review ──Publish (admin)──▶ Published vN
            ▲                          │                             │
            └───── Return to draft ────┘        Edit course ─▶ new Draft (v N+1, cloned)
```

- A course has **at most one open version** (draft or in review) — a database constraint.
- Only a plain draft is editable. In-review, published and archived versions are locked (409).
- Publishing archives the previous published version; anyone pinned to it keeps it
  (enrollments will reference `CourseVersion`, never `Course`).
- Submit and Publish run the **publish checklist** (≥1 module with ≥1 lesson, no empty
  lessons, every activity fully configured). Drafts may hold unfinished activities
  ("Needs setup"); publishing may not.
- Publishing needs `catalog.publish_courseversion` (Admin). Authoring needs
  `catalog.author_content` (Trainer, Admin). The session reports what the user may do
  (`capabilities`) so the UI can show or hide things; every endpoint still calls `can()`.

## Writing lessons (Markdown conventions)

Plain Markdown, plus:

```
> [!IDEA]                    Key idea        (teal tint block)
> [!WHY]                     Why it matters  (eyebrow + prose)
> [!SUPPORT]                 Support lens    (teal rule)
> [!SCENARIO] Optional title Customer scenario (neutral surface; nest a quote for the customer's words)
> [!PITFALL]                 Common pitfall  (amber)
> [!TAKEAWAY]                Takeaway        (closing rule + bullets)

```flow
Source -> Extract -> Load* -> Destination      (* highlights a step)
```
```

These are primitives, not a template — use the fewest that help. The editor's
"Insert" toolbar adds them; "Preview" uses the real learner renderer. Raw HTML is
never rendered.

The course overview is Markdown too: a lead, then `## What you'll learn` bullets.

## Importing a curriculum

Studio → course → **Import**: upload `.csv` or `.xlsx` (≤ 2 MB, ≤ 2,000 rows).

Recognised columns (case/spacing-insensitive; legacy names work): **Module**
(Segment), **Lesson** (Topic), **Section** (Subtopic), Description, Minutes,
Activity, Activity type (Reading, Video, PDF, Quiz, Workshop, External course,
Simulation, Chat simulation), Required, Points, URL. Blank hierarchy cells repeat
the one above. The wizard shows the detected mapping, row-numbered errors and the
resulting tree before anything is written; commit is all-or-nothing and appends to the
open draft. The spreadsheet is never the source of truth.

## API (all under `/api/v1/authoring/`, session auth, CSRF)

`activity-types/` · `courses/` · `courses/{id}/` (GET, PATCH overview) · `courses/{id}/draft/` ·
`courses/{id}/preview/` · `courses/{id}/nodes/` · `courses/{id}/publish-checklist/` ·
`courses/{id}/submit|publish|return-to-draft/` · `courses/{id}/import/preview|commit/` ·
`nodes/{id}/` · `nodes/{id}/impact/` · `nodes/{id}/order/` · `nodes/{id}/activities/` ·
`nodes/{id}/activities/order/` · `activities/{id}/`.

Learner endpoints (`/api/v1/catalog/*`) are unchanged apart from an additive `course_id`;
they only ever serve published versions and expose only each activity type's learner-safe
`config` (a reading's link; a quiz's questions and choices — never its answers).

## Quizzes

A quiz (`mcq`) is edited with plain fields (question, choices, which are correct, optional
explanation, pass mark, attempts allowed) and stored as
`{questions: [{text, choices, answer: int | [int], explanation?}], pass_threshold}`.
A question is right only when the picked set equals the correct set; the score is
right ÷ total and the learner passes at `pass_threshold` (default 70%). New quizzes allow
unlimited attempts (`max_attempts = 0`); set a number to cap them.

Learners take it one question at a time (Next / Back, Submit on the last), then see the
percentage, what was needed and their attempts left. They get questions and choices only:
after a try they see right/wrong per question; the correct answers and explanations are
revealed once they pass or spend their last attempt, so a failed try can't be turned into a
pass. Passing completes the activity (and counts toward the lesson gate); a pass is
permanent.

Using every attempt without a pass **finishes** the quiz as "Not passed": it is grayed out,
no longer blocks the lesson, and the learner can continue. Every try is recorded in
`progress.ActivityAttempt` (score, per-question verdicts, the learner's picks, timestamp), so
scores are never lost; learners see their own history under "View results". The author
preview shows the questions but scores nothing.

Re-testing: with `ALLOW_ATTEMPT_RESET` on (dev settings turn it on; it is off by default)
a signed-in user sees "Reset attempts" on a quiz they have tried, which deletes their own
attempts and reopens the lesson. Production leaves it off until trainers get a proper screen.

## Known limits

- Every trainer can edit every course (the `_scope_check` seam in `accounts/rbac.py` is ready for per-course ownership).
- Last write wins; reorder sends the full id list. No collaborative editing.
- No cross-parent moves, no replace-mode import, no live Google Sheets link (download CSV/XLSX).
- Quizzes: single and multiple choice only — no shuffling, short answer, ordering, question banks or partial credit.
- Trainers can't reset or view a learner's quiz scores yet (Django Admin → Activity attempts shows them; delete the attempts and the learner's progress row to reset).
- Submitting has no notification yet — admins see a "waiting to be published" queue in the Studio.
