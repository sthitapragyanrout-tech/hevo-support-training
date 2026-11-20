# Certificates, the Dashboard and groups

## Certificates

A course earns a certificate when it is switched on in **Studio → Settings → Certificate**. That's a course setting, not part of a version, so it applies immediately without publishing. Every change is audited (`certificates.policy`).

**Earned when**, for a learner actively enrolled on the course:

1. every required lesson is done (a lesson waiting for marks doesn't count);
2. each kind of scored work the course weighs has at least one result;
3. the **course score** reaches the passing threshold (whole percent, default 70).

**Course score (interim rule):** see `apps/certification/scoring.py`.

- Each kind of work is averaged:
  - quizzes by their best score;
  - practice tickets by their average, out of 5;
  - mentor-rated work by its latest rating, out of 5 (waived work is left out).
- The kinds are then combined by the course's weights (default 1 : 1 : 1).
- A kind the course doesn't have is skipped. A weight of 0 leaves a kind out.
- A course with no scored work is earned by finishing it.

This rule stands in until the questions in [scoring-open-questions.md](scoring-open-questions.md) are settled. It lives in one function, and its numbers are data.

**Issuing:** `certification.services.evaluate` runs after anything that can change the result, once that change is committed:

- a quiz attempt or a written answer being marked;
- a practice ticket;
- a lesson completed;
- work rated;
- a version move;
- a re-enrollment;
- a policy change.

For back-filling, run `manage.py evaluate_certificates [--course <slug>]`.

The learner gets a notification and a printable page at `/certificates/<code>`; the browser's print dialog saves it as a PDF.

**Never taken back automatically.** Raising the threshold later, resetting attempts or switching certificates off leaves issued ones alone. Only someone with `enrollment.manage_enrollments` can revoke one, with a reason, from the learner's page, and that is audited. A revoked certificate is never re-issued automatically; it can be restored.

**What each person sees:**

- **Learners:**
  - their score so far against the pass mark;
  - what is still missing;
  - the certificate itself;
  - never the per-kind breakdown, because one of its parts is the mentor's average.
- **Staff:** the breakdown and the snapshot (score, threshold, weights) taken when the certificate was issued.

## Dashboard (Admin → Results → Dashboard)

The Dashboard has one row per active enrollment, with these columns:

- name and email;
- employee id;
- course;
- group;
- progress;
- quiz score (the average of each quiz's best score);
- course score;
- certificate;
- last activity.

It can be sorted by any column and filtered by search, course, group (or no group) and certificate status. "Export this list" downloads the same rows as a CSV. "Export every attempt" is the older attempt-level CSV. Both exports are audited.

Each row opens the learner's page. That page shows every course they are on now (at their pinned version) laid out like their own My progress, plus the staff-only details: every attempt, mentor scores, the certificate panel and attempt resets. Work on older versions folds under "Earlier versions".

The old Results → Learners list redirects to the Dashboard.

**Cost:** each row is built from the same summary as My progress, about 20 queries per row. The list refuses more than 1,000 enrollments at once and asks for a course or group filter instead.

## Groups

**Groups are Programs.** The Console calls them Groups (L1, L2, …).

- A group is still a named, ordered set of courses that can be enrolled together.
- An existing enrollment can be put in a group, moved to another, or taken out, from Enrollments → **Group**. This is audited as `enrollments.group`.
- Only a group that includes the course can be chosen.
- A group is a reporting label: it doesn't change what the learner can open.
