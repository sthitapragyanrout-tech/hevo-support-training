# Notifications

People are told, inside the platform, when something that concerns them changes: a bell in the
header with an unread count, a short dropdown, and a full list at `/notifications`. **In-app only for
now.** There is no email, no Slack, no per-person settings and no mute; the code leaves one place for
email to be added later (see *Adding email*).

## What gets sent, to whom

| Event | Who is told | Where it happens |
|---|---|---|
| Enrolled on a course (or enrolled again) | the learner | `enrollment.services.enroll` (not when they were already enrolled) |
| Moved to a newer version of a course | the learner | `enrollment.migration.apply` (never by the preview) |
| Their modules were changed | the learner | `enrollment.modules.set_modules`, only if the set actually changed |
| Written quiz answers marked | the learner (passed / not passed, percent) | `manual_sim.quiz_reviews.rate` |
| Practice simulation rated (passed, or changes requested with a new date) | the learner | `manual_sim.services.rate` |
| New simulation or written quiz waiting for review | their mentor; with no mentor, every eligible rater (never the learner) | `manual_sim.services._submit`, `quiz_reviews.submit` |
| Work was handed to you | the new mentor, one notice with a count | `manual_sim.assignments`, `reassign` |
| A simulation is due within a day / has passed its deadline | the learner | the sweep |
| A review you were given is overdue | the assigned mentor (managers if it is in the pool) | the sweep |
| A review is overdue past the escalation grace | trainers and admins (`manage_reviews`) | the sweep |
| N learners are past a deadline | trainers and admins, **one digest per day** | the sweep |

Texts are plain and written for the reader. A learner is never shown a reference answer or another
learner's name; mentors and trainers see the learner's name, which they can already see in the queue.

## How it behaves

* A notice is written **in the same transaction** as the thing it reports. If the rating rolls back,
  so does the notice: nobody is told about something that did not happen.
* It is written inside a savepoint and **any error is logged and swallowed**: a bug here can never
  stop an enrollment or a rating.
* Every notice may carry a `dedupe_key`, unique per person. Writing the same key twice is a no-op, so
  jobs can run any number of times (or at the same time) and never repeat a message. Deadline keys
  include the deadline, so **extending a deadline announces it again** and an unchanged one never
  repeats.
* "Waiting" notices are marked read automatically when the work is rated, withdrawn or reassigned
  (`resolve(prefix)`), so a mentor's bell does not keep counting finished work.
* Links must be paths inside the app (start with a single `/`); anything else is dropped.

## The sweep

`notifications.sweep` runs every 15 minutes from Celery beat (default `media` queue, like the other
beat jobs, so `make dev-workers` runs it). It only looks at the database, so a missed run is simply
caught up by the next. Details worth knowing:

* Open cases only: not closed, passed, waiting for review, withdrawn, deactivated or in a module
  switched off for that learner.
* "Overdue" is announced only for deadlines that passed in the **last 14 days**, so switching the
  feature on never floods anyone with old history.
* Nothing here changes any work. Overdue is only ever shown, as everywhere else in the platform.

`notifications.prune` runs daily at 03:30: read notices older than 90 days and any older than 180 are
deleted.

## API (`/api/v1/notifications/`, signed-in, your own rows only)

| Call | Purpose |
|---|---|
| `GET /` | newest first, paged (`page`, `page_size`), `?unread=1`; includes `unread_count` |
| `GET unread-count/` | the light call the bell polls |
| `POST <id>/read/` | mark one read (someone else's id is a plain 404) |
| `POST read-all/` | mark all read |

Throttle: `notifications` scope, 120/min.

## Frontend

* `NotificationBell` in the app header (hidden while a temporary password must be replaced), with an
  unread count that disappears at zero and reads "99+" past 99. Clicking opens the latest eight with
  *Mark all read* and *See all notifications*.
* `NotificationsContext` refreshes the count on load, **once a minute only while the tab is visible**,
  and when the window regains focus. A failed refresh is silent: the bell keeps the last count and
  nothing on the page is blocked. No websockets, so a new notice appears within about a minute.
* Opening a notice marks it read and goes to its link.

## Adding email

`notifications.services.deliver(notification)` is called for every new notice and does nothing today.
Email means implementing it (send on commit, honouring a per-person preference) and adding the
preference; the events, keys and tests stay as they are.

## Limits

* A pooled item notifies **every** eligible rater. Fine for a small team; if it grows, switch the
  pool to a managers-only or counter notice.
* Bulk and program enrollment send one notice per course.
* Work moved back to the pool is not announced, and "waiting" notices that were sent before a mentor
  was assigned stay unread until the work is done.
* Someone who loses a role keeps their old unread notices; the link simply shows what they can see.
* Reminders are only as fresh as the 15-minute sweep.
* Notices are text snapshots: renaming a course later does not change old text.
* Nothing for withdrawals, course publishes, or practice-ticket results.

## Tests

`test_notifications_core.py` (service, API, privacy), `test_notifications_events.py` (each event and
who is told), `test_notifications_sweeps.py` (each reminder, re-running adds nothing, extensions,
exclusions), `test_enrollment_concurrency.py` (Postgres: sweeps at once raise each reminder exactly
once), `test_worker_isolation.py` (the two tasks route to `media`), and
`frontend/src/features/notifications/notifications.test.tsx`.
