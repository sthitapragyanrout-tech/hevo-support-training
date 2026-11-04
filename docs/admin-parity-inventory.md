# Django Admin → Admin Console: feature-parity inventory

Single source of truth for retiring Django Admin. **Django Admin is NOT retired until every row
below is `Replaced` (with tests) or an `Intentional difference` the owner has signed off.**
Until then it stays reachable as restricted emergency access (see "Emergency access").

Status legend: `Not started` · `In progress` · `Replaced` (built + tested + verified in the browser) ·
`Intentional difference` (deliberately not replicated; reason given) · `Studio` (owned by the
existing authoring tool) · `n/a`.

Last updated: **All planned phases implemented and tested** — foundation + learner results, audit log, users & roles (including administrator-created roles), courses back-office (Phase 3), sign-in logs (`AccessLog`/`AccessFailureLog`) and own-password change. Owner decisions recorded below. **Django Admin stays enabled as restricted emergency access** until the owner signs off the retirement checklist at the bottom.

## Owner decisions (recorded 2026-10-23)

1. **Users are deactivated, never deleted** — preserves learner score history. Final.
2. **SSO identities are read-only in the console** for V1; editing stays in restricted Django Admin until SSO ships. Final.
3. **Order of work:** Phase 3 (courses) → axes login logs → own-password change. Done.
4. **Administrators can add roles and assign permissions** (built-in roles protected). Done.
5. **Django Admin stays enabled (superusers only) until all gaps are implemented, tested and the inventory is complete.**

## Emergency access (restriction, kept until parity)

| Item | Before | Now |
|---|---|---|
| URL | `/admin/` | `/django-admin/` (the SPA owns `/admin`) |
| Who may enter | any `is_staff` user | **active superusers only** (`AdminSite.has_permission`) |
| Switch | always on | `ENABLE_DJANGO_ADMIN` setting (default on; flip off in production once parity is signed off) |
| Header | "Django administration" | "Emergency back-office" (verified: `test_emergency_admin.py`) |
| Audit | Django `LogEntry` (admin changes only) | unchanged, plus console actions go to `audit.AuditLog` |

## Admin site-wide features

| Feature | Django Admin | Console replacement | Status |
|---|---|---|---|
| Login | `/admin/login/` (staff) | SPA login (existing) | Replaced |
| Sidebar ordering | catalog, accounts, auth, axes | Console left rail (Results, Activity; People in Phase 2), capability-gated | Replaced (Phase 1 sections) |
| Object history | per-object "History" (`LogEntry`) | Audit log screen (search by person/target, filter by action) | Replaced for console actions |
| Search / filters / pagination | per ModelAdmin | `DataTable` (server-side paging, sorting; search + filters per screen) | Replaced (shared component built + tested) |
| Bulk "delete selected" | default action on every list | Not replicated (users are deactivated, not deleted; see Users) | Intentional difference |
| Password change page | `/admin/password_change/` | **Change password** (account menu) for your own password; also the forced screen for anyone signing in with a temporary or reset password. Re-checks the current password through django-axes, applies the strength rules, signs other sessions out, is audited | Replaced (`test_change_password.py`, `account.test.tsx`, browser-verified) |

## accounts

| Model / admin | What Django Admin does today | Permission | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|---|
| `User` (`UserAdmin`) | list: username, email, employee_id, is_active, is_staff · filters: is_staff, is_superuser, is_active · search: username, first/last name, email · add form (username, **email**, password1/2) · edit: names, email, active/staff/superuser, last_login, date_joined, employee_id, must_change_password, timezone · change password · delete · inline role assignments | `accounts.manage_users` (add/change/delete) | **Users** (list with search, role/status/locked filters, sort, paging; Add user; detail with profile edit, deactivate/reactivate, set password, require a password change, unlock, roles, emergency-access flags) | Replaced (with intentional differences) | `test_console_users.py` (permissions, list, detail, create, update, password, unlock, roles), `people.test.tsx`, browser-verified at 1440 and 390px | **Delete → deactivate only** (keeps attempt history; Intentional difference). `is_staff`/`is_superuser` editable only by superusers, and never on yourself. No filter on staff/superuser flags (shown on the user page). `last_login`/`date_joined` shown, not editable. The Django-admin password-hash "change password" form is replaced by *Set password*. |
| `UserIdentity` | list: user, provider, external_id, email · filter: provider · add/edit/delete | `accounts.manage_users` | Read-only list on the user page (SSO is unused in V1) | Intentional difference (read-only) | `test_console_users.py::TestDetail` | Editing identities stays in emergency admin until SSO ships. Needs owner sign-off. |
| `Role` | list: name, permission count · add/delete · edit permissions (filter_horizontal) | `accounts.manage_roles` | **Roles**: role × capability matrix, member counts linking to Users; **Add role** (name + abilities), rename and delete roles you added | Replaced (with intentional difference) | `test_console_roles.py` (matrix, safeguards, custom roles, rename/delete, options), `people.test.tsx`, browser-verified | Only the console's known capabilities can be granted; arbitrary Django permissions cannot (deliberate). The four built-in roles can't be renamed or deleted; a role anyone still holds can't be deleted. The Admin role always keeps Manage users + Manage roles. |
| `RoleAssignment` | list: user, role · filter: role · add/delete | `accounts.manage_roles` | Roles tab on the user page; "who holds this role" = Users filtered by role (the Roles screen links there) | Replaced | `test_console_users.py::TestRoles` | Guards: cannot remove your own Admin role; cannot remove the last administrator. |
| `auth.Group` | unregistered | — | n/a | n/a | — | Reserved for future isolation. |

## catalog

| Model / admin | What Django Admin does today | Permission | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|---|
| `Course` | list: slug, title, created_by, created_at, archived_at · search: slug · add/change/delete | author_content (add/change), publish_courseversion (delete) | **Courses** (list across every state with search and status filter; detail with version history; **Archive / Restore**, audited) + Studio for creating and editing | Replaced (with intentional difference) | `test_console_courses.py` (permissions, list, filters, detail, archive effects), `courses.test.tsx`, browser-verified at 1440 and 390px | **Delete → archive/restore** (same reasoning as users: keeps history; needs the owner's explicit sign-off). Archiving hides the course from learners, blocks new progress and drops it from Studio's list; nothing is deleted. Slug editing is not offered (slugs are stable URLs). |
| `CourseVersion` | list: version, course, state, published_at/by · filter: state · **action: Publish selected** · change/delete | publish_courseversion | Version history on the course page (state, content size, learners who started it, who submitted/published and when); **publishing stays in Studio's Admin-only flow** | Replaced / Studio | `test_console_courses.py::TestDetail`, existing authoring tests for publish | Version rows are read-only in the console; deleting a version isn't offered (published versions are history). |
| `ContentNode` | tree list with drag-reorder, "+ add child", inline `Activity` editing with JSON `config` | author_content (locked for non-draft unless superuser) | Studio curriculum builder + activity editors (quiz editor, schema form) | Studio | existing Studio tests | Superuser corrections to published nodes remain emergency-admin only (Intentional difference). |
| `Activity` | inline on ContentNode only | author_content | Studio activity editors | Studio | existing | — |

## progress

| Model / admin | What Django Admin does today | Permission | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|---|
| `ActivityProgress` | list: user, activity, state, started/completed · filter: state · search user/activity · no add | default | Learner results → learner detail (per-activity state) and Quiz results (states per learner) | Replaced | `test_console_results.py` (detail, quiz detail), `admin.test.tsx` | No free-text search by activity title (the Quizzes screen lists activities instead). |
| `LessonCompletion` | list: user, node, completed_at, provisional · filter: provisional · search · no add | default | Learner results: lessons completed (list column and per course in detail) | Replaced | `test_console_results.py::TestLearnerList/Detail` | Per-lesson completion dates are not shown (only counts). A *provisional* lesson (moved past while a mentor's rating is awaited) is excluded from the counts. |
| `ActivityAttempt` | list: user, activity, number, score, passed, submitted_at · filter: passed · read-only · no add/change · **delete = the only way to reset a learner** | default | Learner detail (every attempt with score, date), Quiz results, **Reset attempts** (`progress.manage_attempts`, audited, confirmed), CSV export (audited) | Replaced | `test_console_results.py` (permissions, detail, reset, export, audit), `admin.test.tsx` (detail, reset dialog), browser-verified at 1440 and 390px | Reset also removes the progress row and reopens the lesson (same rule as the learner dev reset). No "passed only" filter on attempts (Quiz results shows passed/not-passed per learner). Emergency admin keeps the raw table. The CSV has a **Type** column and a **Score out of 5** column: a practice ticket is never written as a percent (its *Score %* cell is blank), and "Quiz attempts" on the learner list counts quizzes only. |

## axes (django-axes lockouts)

| Model / admin | What Django Admin does today | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|
| `AccessAttempt` | list failed-login attempts per ip/username; delete = unlock | Users: "Locked out" filter and badge; **Unlock now** (audited) | Replaced | `test_console_users.py::TestList/TestUnlock`, `people.test.tsx` | The raw per-IP attempt rows (ip, user agent, timestamps) are not shown. |
| `AccessLog` | login/logout log: time, logout time, ip, username, user agent · filters: attempt/logout time, path · search | **Sign-in activity → Sign-ins** (account linked to the user, address, browser, signed-out time; search; date range) + link from the user page | Replaced | `test_console_signins.py`, `signins.test.tsx`, browser-verified | Read-only; no path filter (all rows are the login endpoint). |
| `AccessFailureLog` | failed-login log with locked-out flag · filter: locked_out | **Sign-in activity → Failed attempts** (+ "Only lockouts") | Replaced | same, plus the setting test | **Behaviour change:** `AXES_ENABLE_ACCESS_FAILURE_LOG` is now on (axes keeps no failure log otherwise — found by browser testing). History before this change does not exist. |

## media_pipeline and video watching (new in Module 7)

| Model / admin | What Django Admin does today | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|
| `MediaAsset` | read-only list: name, status, uploader, length · filter: status · search | Uploads, processing status and retry live in Studio's video editor (uploader and administrators only) | Studio (list also kept read-only in emergency admin) | `test_media_*`, `videoEditor.test.tsx` | No console screen listing every upload yet; originals are deleted after a verified conversion by default. |
| `VideoWatch` | read-only list: learner, video, credited seconds, needs review · filter | **Results → learner page**: each video shows *Watched N%* and, when something is unusual, *Worth a look* with plain reasons | Replaced | `test_console_results.py::TestVideoRows`, `admin.test.tsx` | No cross-learner "needs review" queue yet; resetting a learner's video progress is not offered (completion is permanent). |

## bot_sim — practice tickets (new in Module 9)

| Model / admin | What Django Admin does today | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|
| `Scenario` | read-only list (emergency access only): summary, topic, persona, status, source · filters · search; no add or change | **Content → Practice scenarios** (`catalog.author_content`): filter (status, topic, customer type, source, needs attention, one import), read in full, edit, **Approve / Reject / Retire / Restore**, write one, **Generate drafts**; shows source, automatic approval, ticket id, how it's doing (finished, average, skips by reason) and why it needs a look; every change audited | Replaced | `test_sim_scenarios.py`, `test_sim_quota.py`, `test_sim_import.py`, `practice.test.tsx` | No bulk approve. No delete (retire instead). Reference-answer text is stored but not yet used by the scorer. |
| `ScenarioImport` | not registered | **Past customer queries** panel: *Import from Zendesk* (administrators), live progress, a result per run with plain-language reasons, *Show these questions*, *Send N back to draft*; start, refusal and undo are audited | Replaced | `test_sim_import.py`, `practice.test.tsx` | Import is refused until the data-protection sign-off is recorded in the environment and a sample audit has run (`audit_zendesk_sample`); the Console cannot grant either. |
| `PracticeSettings` | not registered | The **automatic approval** switch (administrators, audited; the environment variable overrides it) | Replaced | `test_sim_import.py`, `practice.test.tsx` | The audit timestamp and counts are shown, not editable. |
| `SimSession` | read-only list: learner, activity, state, preview, started, tokens · filters: state, preview · search by learner | **Results → learner page** (tickets finished of N, average, questions skipped; each ticket with score, above/below the pass mark, "Worth a look" reasons; skipped questions listed apart) → **transcript** (`/admin/results/sessions/<id>`, `progress.view_results`) | Replaced | `test_console_results.py`, `practice.test.tsx` | No cross-learner "needs review" queue beyond the scenario filters. Resetting a learner's attempts (`progress.manage_attempts`) also abandons any ticket they have open. |
| `SimTurn` | not registered | shown inside the transcript (text, role, time, turnaround, scores, job state and error) | Replaced | as above | Lease and attempt counters are not shown anywhere in the console. |
| `LLMCall` | read-only list: time, task, model, status, tokens, latency · filters: task, status | Totals shown per ticket (tokens, models); individual calls stay in emergency admin | Intentional difference (needs sign-off) | `test_sim_gate.py` | No cost dashboard. |
| `LLMBudget` | not registered | none (operational state: the rate window, day total and breaker; the breaker clears itself after its cool-down) | Intentional difference | `test_sim_gate.py` | No console switch to pause practice; use `SIMBOT_ENABLED`. |

## manual_sim — mentor-rated simulations (new in Module 6)

| Model / admin | What Django Admin does today | Console replacement | Status | Tests | Gaps |
|---|---|---|---|---|---|
| `SimSubmission` | read-only list (emergency access only): case, revision, state, routing, late, times · filters · search by learner | **Review → Ratings** (`manual_sim.rate_submissions` / `manage_reviews`): the queue (Mine, Shared pool, All waiting, Needs a trainer), the rating page (task, rubric with raters' guidance, the whole thread, per-criterion scores, draft, submit), claim / release / take over / reassign; each action audited | Replaced | `test_manual_sim_api.py`, `test_manual_sim_services.py`, `ratings.test.tsx` | Ratings are final; there are no amendments. |
| `SimCase` | read-only list | **Results → learner page** (status, revisions, deadline, overdue, needs attention) with **Extend, Waive, Close, Reopen** (`manage_reviews`, reason required, audited) | Replaced | `test_manual_sim_services.py`, `test_manual_sim_progression.py`, `ratings.test.tsx` | |
| `RubricScore` | read-only list | shown inside the thread and to the learner (score, label, feedback) | Replaced | `test_manual_sim_api.py` | |
| `SubmissionFile` | read-only list | opened from the thread / the learner's own screen, authorised on every request | Replaced | `test_manual_sim_files.py` | No antivirus scan; the orphan sweep is a command (`purge_orphan_attachments`). |
| `MentorAssignment` | read-only list | **none yet** — written only through `assign_mentor()`, whose caller will be the enrolment workflow | Intentional difference (needs sign-off) | `test_manual_sim_services.py` | Until enrolment exists nothing writes it, so all work uses the shared pool. |
| Rating permissions | the two permissions on the role matrix | **Admin → Roles** shows *Rate simulations* and *Manage simulation reviews* (Admin keeps the latter) | Replaced | `test_manual_sim_config.py`, `test_console_roles.py` | |

## audit (new)

| Item | Status |
|---|---|
| `audit.AuditLog` model (actor, action, target, summary, ip, timestamp; secrets scrubbed) | Replaced (`test_audit.py`) |
| Written by every console mutation: reset attempts, results export, user create/update/deactivate/reactivate/set password/unlock/roles, role permissions (never secrets) | Replaced (`test_console_*`) |
| Viewer (`audit.view_audit`, admin only) with search and action filter | Replaced (`test_console_audit.py`, `admin.test.tsx`) |

## Capabilities introduced

| Action | Granted to | Used for |
|---|---|---|
| `progress.view_results` | trainer, admin | Learner results, quiz results, export |
| `progress.manage_attempts` | trainer, admin | Reset a learner's quiz attempts |
| `audit.view_audit` | admin | Audit log viewer |
| `accounts.manage_users` / `accounts.manage_roles` | admin (existing) | Users & Roles screens |

## Retirement checklist (all must be ticked, then owner sign-off)

- [x] Every row above is `Replaced`, `Studio` (verified) or a recorded `Intentional difference`
- [ ] **Owner sign-off still needed on:** course delete → archive/restore; version deletion not offered; no arbitrary Django permissions; superuser corrections to published nodes stay in the emergency admin; failure-log setting change
- [x] Each console mutation writes an `AuditLog` row (tests)
- [x] Backend permission tests for every endpoint (anonymous 403, wrong role 403, right role 200)
- [x] Browser verification at 1440 and 390px for every screen
- [x] Emergency access verified superuser-only (`test_emergency_admin.py` + browser)
- [ ] **Owner sign-off to set `ENABLE_DJANGO_ADMIN=false` in production** — until then Django Admin stays enabled (superusers only)

## Known limits worth knowing

- **Forced password change is OFF by default** (owner request, to ease testing): `ENFORCE_PASSWORD_CHANGE` (env var, default false). Accounts are still *flagged* and the voluntary "Change password" screen always works. When switched on, the app redirects flagged accounts to the change screen and hides navigation; the API itself does not refuse other calls from such a session.
- Archiving a course ends progress recording on it; reopening requires Restore.
- Django Admin keeps working for everything above, including the raw `AccessAttempt` rows and identity editing.
