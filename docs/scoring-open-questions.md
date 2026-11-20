# Scoring and results: what to settle before Module 8b

**Status (updated 2026-11-21):** an *interim* course score and certificates now exist (see
[certificates.md](certificates.md)): per-kind averages combined by per-course weights, and a per-course pass mark, all editable
data. The questions below still decide the final rule; answering them means changing
`apps/certification/scoring.py`, not the data model.

**Original status: nothing here was built, on purpose.** Module 8b (a weighted roll-up, certificates, the
verify page, cohort exports and the admin dashboard) depends on rules that belong to the business, not
to the code: how results combine, what "passing" a program means, and who sees which number. Building
it on guesses would mean rebuilding it. This page lists the questions, the realistic options, what we
would suggest as a default, and what the platform already records, so the conversation with your
manager can be short and the answers can be turned straight into a plan.

Everything below stays **editable data** (weights, pass bars, scales live in rows or settings, not in
code) whichever way the decisions go.

## What the platform already records (the raw material)

| Source | What is stored per learner | Scale |
|---|---|---|
| **Quiz** (`ActivityAttempt`) | every attempt: score, passed, per-question result, number, time. Written questions: marks per question and the marker's comment (`QuizReviewMark`). Attempt limit and pass mark are per quiz. | score 0–1 (whole-percent pass mark) |
| **Practice ticket** | every finished ticket: score, plus per-reply communication, empathy, accuracy, concreteness (1–5). Completion = N scored tickets; an optional "average of the last N must reach the pass mark". | 1–5, never a percentage |
| **Mentor-rated simulation** | every revision: a 1–5 score per rubric criterion, the average, pass/fail, the mentor's comment, deadlines, lateness, who rated and when. | 1–5, never a percentage |
| **Reading, video** | completion; for video, the verified fraction watched. | done / not done |
| **Lessons** | completion, and "complete pending marks" (provisional). | done / provisional |
| **Enrollment** | which course version they are pinned to, program, mentor, withdrawn, version moves (with what was carried or left behind). | n/a |
| **Audit log** | every administrative action. | n/a |

What is **not** recorded: any weight, any competency a score belongs to, any program-level result,
any rank, any certificate. Those are the 8b questions.

## The questions

Each has a suggested default. The default is only a suggestion to react to; "none of these" is a fine
answer.

### 1. What is rated: each attempt, or the program as a whole?
Options: (a) the **program** gets one result computed from the best or latest work in each part;
(b) every **attempt** is rated and the program is the sum of attempts.
*Suggest (a):* learners retake things; one result per part is easier to explain than a pile of attempts.
*Affects:* the shape of the roll-up, and what the learner sees.

### 2. When there are several ratings, how do they combine?
Options: best, latest, average of all, average of the last N (practice tickets already do this),
or "first pass". Mentor-rated work has revisions: is the *final* revision the result, or the average?
*Suggest:* best for quizzes, last N average for practice tickets (as built), final revision for rated work.
*Affects:* retakes, and whether a learner can "game" a part by repeating it.

### 3. What are the scales, and may they be shown together?
Quizzes are 0–100%, practice and rated work are 1–5, readings and videos have no score. Options:
(a) keep scales apart and only combine through *weights over normalised values*; (b) convert everything
to one scale; (c) never combine, show pass/fail per part.
*Suggest (a)* with the normalisation written down once (for example 1–5 mapped to 0–100%).
*Affects:* whether an overall number exists at all.

### 4. Is there an overall score, a per-competency view, or both?
The design documents mention competencies (communication, empathy, accuracy, concreteness, ...). Options:
(a) a single weighted overall; (b) a score per competency, no overall; (c) both.
Mapping needs answering too: which activities feed which competency, and in what proportion?
*Suggest:* start with (a) plus the practice-ticket competency breakdown that already exists, and add
a mapping table only when someone can name what they would do with it.
*Affects:* the biggest piece of 8b; also what the learner dashboard can honestly show.

### 5. What does it take to pass the program?
Options: an overall bar only; a bar **per competency or per part** as well ("no part below X");
mandatory parts regardless of score (for example the final one-to-one). Is a part optional if it is
marked optional in the course?
*Suggest:* overall bar plus "every required part completed", with an optional floor per part.
*Affects:* certificates and eligibility.

### 6. Do rank, flags or review notes affect certification?
Today the platform has "needs attention" flags (several unsuccessful reviews) and late/overdue marks.
Options: purely informational; or a flag can block certification until a trainer clears it.
*Suggest:* informational only. Anything that blocks a certificate should be an explicit decision by a
person, recorded in the audit log.

### 7. How do deadlines and lateness count?
Late work is accepted and marked late today. Options: no effect on the result; a penalty; a cap.
*Suggest:* no effect on the score; lateness is reported, not scored.

### 8. What happens to results across versions and retakes?
Learners are pinned to a version and moved on purpose (unchanged results carry over, changed ones stay as
history unless carried). Options for the roll-up: use only the pinned version's results; or allow
carried-over results to count. A trainer can also reset a learner's quiz attempts.
*Suggest:* count what is on the learner's pinned version, including carried results, and keep a
snapshot of the inputs on every roll-up so a result can always be explained later.

### 9. Written quiz answers
They are marked in whole marks against a reference answer. Is that precise enough, or does a competency
need a rubric (criteria scored 1–5) the way mentor-rated work has? If a written question is marked
differently by two mentors, who is right?
*Suggest:* keep whole marks for now; revisit if mentors disagree in practice.

### 10. Who sees which number?
Options for the learner: pass/fail only; their own scores per part (as My progress shows today); their
overall; their position relative to others (we would not build this without a strong reason).
Options for managers: cohort views and CSV exports. Who may see another team's cohort?
*Suggest:* learners see their own scores per part and the overall once it exists; never other people's.

## Once decided, what gets built

In order, each stage verified before the next:
1. **Roll-up**: a weighted result per learner per program, computed from stored inputs, with the inputs
   snapshotted so any result can be explained and recomputed. Weights, pass bars and the normalisation
   are rows an administrator edits.
2. **Learner view**: the roll-up added to My progress (still facts, now with the rule shown beside the
   number).
3. **Certificate** and the public verify page (name, program, date, serial; no scores).
4. **Cohort export** and the **admin dashboard**.

## The admin dashboard: what it could show

The page exists today as a placeholder. Everything below can already be computed from recorded data,
so it can be built without waiting for the scoring rules (it only reports, it does not decide):
* **Cohort progress**: lessons completed per learner, who has not started, who is behind a deadline.
* **Needs attention**: learners with several unsuccessful reviews, overdue work, or a long-waiting review.
* **Review health**: how long mentors take to mark (median, late, escalated), what is waiting, per mentor.
* **Content health**: for each quiz the pass rate, average best score and how many are stuck; the questions
  most often answered wrongly (from per-question results).
* **Practice tickets**: tickets finished, average score by competency, drop-off.
Not worth building before the rules exist: any ranking, any overall score, any league table.

## For the meeting: questions to take

1. Is a result per program, or per attempt? (Q1)
2. For retakes and revisions, do we count the best, the latest or an average? (Q2)
3. Do we want one overall number, a number per competency, or both? Which activities feed which? (Q3, Q4)
4. What is the pass bar, and are there parts that must be passed on their own? (Q5)
5. Should a flag (repeat failures, lateness) ever block a certificate? (Q6, Q7)
6. What may a learner see: parts, overall, nothing but pass/fail? (Q10)
7. Who may see a whole cohort's results? (Q10)
