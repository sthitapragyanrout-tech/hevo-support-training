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
`nodes/{id}/activities/order/` · `activities/{id}/` · `media/` (upload) · `media/limits/` ·
`media/{id}/` (processing status) · `media/{id}/retry/`.

Learner endpoints (`/api/v1/catalog/*`) are unchanged apart from an additive `course_id`;
they only ever serve published versions and expose only each activity type's learner-safe
`config` (a reading's link; a quiz's questions and choices — never its answers).

## Learning order

Each course has a **learning order**, set in Studio → Settings while the course is a draft:

- **Learners can open any lesson** (default): nothing is locked.
- **Learners go in order**: a lesson opens once every *required* lesson before it is complete.
  Optional lessons never hold anyone up. A quiz counts as finished when it's passed **or** its
  attempts are used up, so a failed quiz slows a learner down but never traps them. A lesson
  that's already complete is never locked.

Learners see locked lessons muted in the sidebar and course page ("Unlocks when you complete …"),
the next lesson marked "Up next", and a calm "not open yet" screen if they follow a link to a
locked lesson. The server refuses to record anything against a locked lesson. The preview shows
everything open and notes that the course is set to go in order. The order is part of the
version, so a published course keeps the order it was published with, and a new draft starts
from the live one.

Limit: locked lessons' text is still in the course payload (the lock is about sequence, not
secrecy).

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

## Videos

A **Video** activity plays inside the lesson — never as a link out. In Studio, choose a source:

- **Upload a video** (MP4, MOV, M4V, WebM or MKV; the limits are shown in the editor — by default
  1 GB and 2 hours). You see real upload progress, then "Processing…" while a background worker
  converts it for the web (you can leave the page), then "Ready · 8:24" with a preview you can
  play. A failed conversion says why, in words, and offers **Try again** when trying again can
  help. You can only use videos you uploaded yourself (administrators may use any).
- **YouTube link** (`youtube.com` or `youtu.be`): played in YouTube's own player inside the lesson.
- **Google Drive link** (`drive.google.com`, a file's share link): played in Drive's own preview
  inside the lesson. Set the file's sharing to "Anyone with the link", or learners are asked to
  request access. Google gives no playback position for Drive, so **watching can't be measured**:
  the learner presses "I've watched this" (like a reading) and trainers see it as *Confirmed by the
  learner*. For watching that is checked, upload the video.

Under **How watching is counted** you set the share of the video that must be watched (default 90%,
50–100) and the fastest playback speed that counts (default 1×). Skipping ahead earns nothing;
the server decides when a video is finished. A draft with a video still processing can't be
published until it shows as ready. In **Preview**, videos play but nothing is recorded.

Processing needs the worker: `make dev-worker` locally (see [media-pipeline.md](media-pipeline.md)).
Without it an upload simply stays on "Processing…".

## Known limits

- Videos: no captions or subtitles, no Vimeo/Loom embeds, no adaptive streaming, and
  watching is verified but can't prove attention (see media-pipeline.md).

- Every trainer can edit every course (the `_scope_check` seam in `accounts/rbac.py` is ready for per-course ownership).
- Last write wins; reorder sends the full id list. No collaborative editing.
- No cross-parent moves, no replace-mode import, no live Google Sheets link (download CSV/XLSX).
- Quizzes: single and multiple choice only — no shuffling, short answer, ordering, question banks or partial credit.
- Trainers can't reset or view a learner's quiz scores yet (Django Admin → Activity attempts shows them; delete the attempts and the learner's progress row to reset).
- Submitting has no notification yet — admins see a "waiting to be published" queue in the Studio.

## Practice tickets

A **Practice ticket** activity puts the learner in a ticket window with an AI customer. It is
**practice, not a test**: finishing enough scored tickets completes it (see [simbot.md](simbot.md)).
In Studio you choose:

- **Customer type** — a mix (random), or one of urgent / technical / non-technical / terse.
- **Topics** — tick the ones to allow; none ticked means any.
- **Tickets to complete** — how many finished, scored tickets complete it (default **5**, 1–20).
- **Pass mark (out of 5)** — default 3.5 (stored as 0.7). It's feedback on each ticket
  ("above / below the pass mark"); it doesn't decide completion. Scores are always shown "x / 5",
  never as a percentage.
- **Replies allowed** (3–6) per ticket, and **Most tickets allowed** (0 = no limit; can't be below
  the tickets to complete).
- **Also require the average of the last N to reach the pass mark** — off by default.

The editor says live how many **approved scenarios** match. A practice ticket **can't be published
with fewer scenarios than the tickets to complete** (a learner could never finish), and warns when
a learner who skips a lot could run out. Learners may skip a question before replying (5 per
activity by default). Scenarios come from past customer queries (read-only import from Zendesk, with
strict automatic checks), from the AI, or by hand — see the Console's **Practice scenarios**.
**Preview** plays the ticket against any scenario — drafts included — and records nothing.

Tickets need the practice worker and a model key: `make dev-workers` and `OPENAI_API_KEY`. Without a
worker a reply simply waits.

## Mentor-rated simulations

A **Simulation (mentor-rated)** activity asks the learner to do a realistic task and hand work in; a
mentor rates it against the rubric you write. In the activity's editor you set the scenario, what to
hand in, the **rubric** (up to 8 criteria; each has a label, "what it looks at" — shown to learners —
and **guidance for raters** — never shown to learners), the pass mark (out of 5), an optional lowest
score per criterion, the days to hand in and to revise (0 = no deadline), a review target, and whether
attachments are allowed. It can't be published until it has a scenario, a labelled criterion, and
someone who can rate (Admin → Roles). Preview shows the task and rubric and records nothing. See
[manual-simulation.md](manual-simulation.md).
