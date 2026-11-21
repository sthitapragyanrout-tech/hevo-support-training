# Hevo Support Training Platform

A training platform for Hevo's support onboarding: trainers author courses, learners work through them
(readings, videos, quizzes, AI practice tickets, mentor-rated simulations), and trainers/admins see results.
It replaces a spreadsheet-and-Google-Forms process (the design is in [docs/architecture.md](docs/architecture.md)).

* **Backend** — Django 5 + Django REST Framework + PostgreSQL, Celery for background work (`backend/`).
* **Frontend** — React 19 + TypeScript + Vite single-page app (`frontend/`).
* **Docs** — design and per-module notes (`docs/`).

> Status: V1 in progress. Built and tested: authoring (Studio), learner experience with ordered
> courses, quizzes, tracked video, AI practice tickets, mentor-rated simulations, **enrollment** (who is
> on which course and version, mentors, programs), and the Admin Console.
> **Not built yet:** the weighted score rollup, certificates, and the Admin dashboard (a placeholder).
> See [What's built](#whats-built).

---

## Quick start (local development, macOS)

You need: **Homebrew**, **PostgreSQL 16** (`brew install postgresql@16`), **[uv](https://docs.astral.sh/uv/)**
(Python 3.12 is managed by it), **Node 20.19+ or 22+**, and optionally **ffmpeg** (`brew install ffmpeg`, only for
uploaded videos). Docker is *not* required for development.

Run everything from the **repository root**; the `make dev-*` targets `cd` into the right folder themselves.

```bash
# 1. Install dependencies (once)
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..

# 2. Database (once). The defaults expect postgres://hevo:hevo@localhost:5432/hevo_training
make dev-db                           # starts Homebrew Postgres
psql postgres -c "CREATE ROLE hevo LOGIN PASSWORD 'hevo' CREATEDB;"
createdb -O hevo hevo_training
make dev-migrate                      # creates the tables
make dev-seed                         # creates the four roles (+ a placeholder course)

# 3. First administrator
cd backend && uv run manage.py createsuperuser && cd ..

# 4. Run it: three terminals, all from the repo root
make dev                              # Django API        → http://127.0.0.1:8000
make frontend                         # the web app       → http://localhost:5173   (open this one)
make dev-workers                      # background jobs: videos, practice tickets, recovery sweeps
```

Settings are optional for a first run. To change any (a different database, the practice-ticket model
key), create `backend/.env` (git-ignored) with just the lines you need; [.env.example](.env.example) lists them.
Don't copy `.env.example` wholesale: its `DATABASE_URL` points at the Docker hostname `postgres`.

`make frontend` proxies `/api` to Django, so keep both running.

Open **http://localhost:5173** and sign in with the superuser you created. A superuser can do everything;
create everyone else from **Admin → People → Users** (see [Roles](#roles)). New accounts get a temporary
password and must change it at first sign-in.

> `make dev-seed` runs `seed_roles`, which **resets the four built-in roles to their defaults**. It overwrites
> permission edits made in Admin → Roles, so don't re-run it on a database you've customised.

### Background workers

`make dev-workers` starts three processes (Ctrl-C stops them all): a **media** worker (video conversion),
a **sim** worker (practice tickets call the language model) and **beat** (the scheduler that runs the
recovery sweeps). You need it for videos and practice tickets; the rest of the app works without it.
Celery uses a filesystem broker (`backend/.celery-broker/`) in development, so no Redis is needed.

Practice tickets need a model key: put `OPENAI_API_KEY=…` in `backend/.env`. Without one, practice shows
"isn't set up yet" and nothing else is affected. `SIMBOT_LLM=fake` uses a scripted model for demos/tests.

### Sample data

```bash
cd backend
uv run manage.py seed_scenarios       # approved sample practice-ticket scenarios (development only)
uv run manage.py seed_placeholder_course   # a small example course (also loaded by make dev-seed)
```

### Tests and checks

```bash
make test                             # backend (pytest) + frontend (vitest)
make lint                             # ruff + mypy
cd frontend && npx tsc -b && npm run lint && npm run build
```

Backend tests use SQLite unless `DATABASE_URL` is set; a few (real worker processes, row-lock races)
need Postgres and skip themselves otherwise.

---

## Using it: who sees what

The app has three areas, chosen by your role. The top bar shows the ones you may use.

### Learners — `/` and `/progress`
* **My courses** lists the courses you are **enrolled** on (if there are none, ask your trainer); open one
  for its overview and a path of modules and lessons. You stay on the version you were enrolled on until a
  trainer moves you to a newer one.
* **My progress** (`/progress`) is your own report across your courses: lessons done of total and what is
  next; each quiz with its attempts, best and latest score (or "awaiting review" while written answers are
  being marked); practice tickets (count, average out of 5, the last few); and mentor-rated work with its
  score out of 5 and the mentor's feedback. Facts only: no overall score, grade or ranking (those wait for
  the scoring rules, see [docs/scoring-open-questions.md](docs/scoring-open-questions.md)).
* In a lesson, work through its activities, then press **Mark complete**. In an *ordered* course a lesson
  stays locked ("Unlocks when you complete …") until the one before it is complete.
* **Activities:**
  * *Reading / link* — open it, then mark done.
  * *Video* — watched in place; credit is based on what you actually watched.
  * *Quiz* — scored on the server, with attempt limits and a pass mark. A quiz can mix single-choice,
    multiple-choice and **written** questions: choice questions score at once, written answers are marked
    by a mentor or trainer (the quiz shows "awaiting review" until then, and the next lesson stays open).
  * *Practice ticket* — a simulated customer conversation scored on communication, empathy, accuracy and
    concreteness; scored out of 5, never a percentage.
  * *Simulation (mentor-rated)* — hand in a written answer (and screenshots/PDF); a mentor rates it against a
    rubric; revise from feedback as often as the deadlines allow. Handing it in opens the next lesson;
    the lesson counts as complete once the rating passes (this is a per-activity setting).
* **Account menu** (top right): change password, log out.

### Studio (authors) — `/studio`
For Trainers and Admins. **Studio → New course**, then in the course builder:
**Curriculum** (modules → lessons → sections, drag to reorder, add activities and configure them),
**Overview**, **Import**, **Settings** (e.g. ordered vs free learning order). **Preview** shows exactly
what a learner will see without recording anything. When ready, **submit for review**; **Admins publish**.
Published versions are immutable; editing a published course creates a new draft.

### Admin Console — `/admin`
For Trainers, Mentors and Admins (each sees only what their role allows). The left rail:

| Section | Page | What it's for |
|---|---|---|
| Results | Dashboard | placeholder (design pending) |
| | Learners | per-learner progress, attempts, practice transcripts, mentor-rated work; CSV export |
| | Quizzes | per-quiz results; reset a learner's attempts |
| Review | Ratings | the mentor queue (**Mine**, **Shared pool**, **All waiting**, **Needs a trainer**) of simulation hand-ins and **written quiz answers**; open one, score the rubric or give marks per written question, send feedback; trainers/admins extend deadlines, waive, close, reopen, reassign |
| Content | Courses | every course and version, archive/restore (authoring itself is in Studio) |
| | Practice scenarios | the question bank for practice tickets: approve, edit, import past customer queries |
| People | Users | create/deactivate users, set passwords, unlock, assign roles |
| | Enrollments | who is on which course and version, their mentor; enroll people or paste a list of emails, **choose which modules each learner gets**, withdraw, change mentor, **move a learner to the newest version** (with a preview) |
| | Programs | named, ordered sets of courses; enroll a whole cohort at once |
| | Roles | the permission matrix; admins can add roles |
| | Sign-ins | successful and failed sign-in log |
| Activity | Audit log | every administrative action |

`/django-admin/` is an emergency back-office for superusers only (it is being retired in favour of the console).

### Roles

| Role | Can |
|---|---|
| **Learner** | take courses |
| **Mentor** | rate mentor-rated simulations (Ratings) |
| **Trainer** | author courses, see results, reset attempts, rate and manage reviews, manage enrollments |
| **Admin** | everything above, plus publish courses, manage users and roles, view the audit log |

Roles are editable (Admin → Roles); permissions are listed in `backend/apps/accounts/rbac.py`.

---

## Typical first session

1. Sign in as the superuser → **Admin → People → Users** → create a Trainer, a Mentor and a Learner.
2. As the Trainer: **Studio → New course**; add a module, a lesson and a few activities (reading, a quiz, a
   mentor-rated simulation); set the learning order; **Submit for review**. As an Admin: **Publish**.
3. As the Trainer: **Admin → People → Enrollments → Enroll people**: choose the course, a mentor, and the learner.
4. Sign in as the Learner (private window): open the course, work through the lesson, hand in the simulation.
5. As the Mentor: **Admin → Ratings → Mine** (work from their mentees) → open the submission → score → send.
6. As the Trainer: **Admin → Learners** to see progress and scores. When you publish a new version of the
   course, learners stay on theirs until you use **Enrollments → Move to newest**.

---

## Configuration

Settings come from environment variables, read from `backend/.env` (see [.env.example](.env.example)).
The important ones: `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DEBUG`, `OPENAI_API_KEY` (practice tickets),
`SIMBOT_*` (practice limits and budgets), `MANUAL_SIM_*` (review targets, upload limits).
Defaults are in `backend/config/settings/base.py`. Never commit `.env`; keep keys out of the repo.

## Repository layout

```
backend/
  apps/accounts      users, roles, permissions (rbac.py), admin services
  apps/catalog       courses, versions, content tree, authoring API
  apps/activities    activity type registry (reading, video, quiz, practice, mentor-rated)
  apps/progress      learner progress, attempts, ordering rules, reports
  apps/bot_sim       AI practice tickets (scenarios, sessions, scoring, workers)
  apps/manual_sim    mentor-rated simulations (submissions, rubric ratings, deadlines, files)
  apps/enrollment    who is on which course/version, programs, the access rule, moving between versions
  apps/notifications in-app notifications: the bell, event hooks, deadline and review reminders
  apps/media_pipeline  video upload, ffmpeg conversion, streaming
  apps/console       Admin Console API
  apps/audit         audit log
  simbot_engine/     the practice-ticket engine (pure Python, no Django)
  tests/             pytest suite
frontend/src/        features/{catalog,studio,admin,…}, components, lib
docs/                architecture and per-module documentation
deploy/              nginx, systemd and backup notes for production
```

## Documentation

* [docs/architecture.md](docs/architecture.md) — the overall design and roadmap
* [docs/authoring-studio.md](docs/authoring-studio.md) — authoring and publishing
* [docs/simbot.md](docs/simbot.md) — practice tickets (flow, scoring, operations, limits)
* [docs/enrollment.md](docs/enrollment.md) — enrollment, programs, the access rule, moving learners between versions
* [docs/notifications.md](docs/notifications.md) — the bell, what each person is told and when, the reminder sweep
* [docs/design-system.md](docs/design-system.md) — the visual language: tokens, surfaces, type, depth, and the rules for extending it
* [docs/certificates.md](docs/certificates.md) — certificates (the interim course score, issuing, revoking), the admin Dashboard and groups
* [docs/scoring-open-questions.md](docs/scoring-open-questions.md) — what must be decided before the scoring roll-up (Module 8b) can be built
* [docs/manual-simulation.md](docs/manual-simulation.md) — mentor-rated simulations
* [docs/media-pipeline.md](docs/media-pipeline.md) — video upload and streaming
* [docs/admin-parity-inventory.md](docs/admin-parity-inventory.md) — Django Admin → Admin Console parity

## What's built

| Area | State |
|---|---|
| Authentication, roles, Admin Console (users, roles, results, audit, sign-ins, courses) | done |
| Course authoring (Studio), versions, publishing | done |
| Ordered/free courses, lesson locking, progress | done |
| Reading, tracked video, quizzes | done |
| AI practice tickets (+ question bank, Zendesk import behind a switch) | done; real-model latency not load-tested |
| Mentor-rated simulations (rubric, deadlines, revisions, uploads) | done |
| **Enrollment** (who is on which course, mentor assignment, version pinning, programs, move to newest version, which modules each learner gets) | done: [docs/enrollment.md](docs/enrollment.md). Learners see only courses they are enrolled on; work from a learner with no mentor goes to the shared pool |
| Weighted scoring rollup, certificates, cohort dashboard | not started (waiting on scoring rules) |
| **Notifications** (bell and list, in-app) | done: [docs/notifications.md](docs/notifications.md). Email, Slack and per-person settings are not started |
| SSO | not started |

## Troubleshooting

* **"Python quit unexpectedly" (macOS) when a practice ticket runs** — a forked worker was killed by the
  Objective-C runtime. `make dev-workers` already sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`; restart the
  workers. If it persists, run the sim worker with `-P threads` (see [docs/simbot.md](docs/simbot.md)).
  A ticket that never finishes now closes itself (uncounted) after about half an hour.
* **A practice ticket sits on "Finishing…"** — the sim worker isn't running (`make dev-workers`) or the model key is missing.
* **Video stays "processing"** — the media worker isn't running, or ffmpeg isn't installed.
* **`manage.py: No such file`** — it lives in `backend/`; use the `make dev-*` targets from the repo root.
* **Locked out after failed sign-ins** — Admin → People → Users → *Unlock* (5 failures / 15 minutes).
* **Port already in use** — a previous `make dev` or `make frontend` is still running.

## Production

See **[DEPLOY.md](DEPLOY.md)**: one Linux server with Docker runs everything
(`docker-compose.prod.yml`: web, workers, Postgres, Redis and nginx serving the frontend).
Settings go in `.env.prod` (template: `.env.prod.example`); backups via `make backup`.
Monitoring and off-server backups are not set up yet (listed at the end of DEPLOY.md).
