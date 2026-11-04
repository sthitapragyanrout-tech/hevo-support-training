.PHONY: up down migrate seed test lint shell backup restore-drill dev dev-db dev-migrate dev-seed dev-shell dev-worker dev-worker-media dev-worker-sim dev-beat dev-workers load-test frontend

# --- Docker Compose workflow (matches the real deployment path in
# docs/architecture.md). Requires Docker — not installed on this machine
# today, so these targets will fail here. Use the `dev-*` targets below
# for local development instead. ---

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose run --rm web uv run manage.py migrate

seed:
	docker compose run --rm web uv run manage.py seed_roles
	docker compose run --rm web uv run manage.py loaddata placeholder_course_tree

shell:
	docker compose run --rm web uv run manage.py shell

# --- Local dev (no Docker) ---
# Runs Postgres via Homebrew and Django directly via uv. This is how local
# dev has actually been happening on this machine. Always run these from
# the repo root — they cd into backend/ themselves, so you never need to
# `cd backend` manually (that mismatch is what broke `manage.py` earlier:
# it only exists inside backend/, not at the repo root).

dev-db:
	brew services start postgresql@16

dev: dev-db
	cd backend && uv run manage.py runserver 127.0.0.1:8000

dev-migrate: dev-db
	cd backend && uv run manage.py migrate

dev-seed: dev-db
	cd backend && uv run manage.py seed_roles
	cd backend && uv run manage.py loaddata placeholder_course_tree

dev-shell: dev-db
	cd backend && uv run manage.py shell

# Background work runs in SEPARATE worker processes, so a slow model call can never
# starve video conversion (or the other way round):
#   dev-worker-media  converts uploaded videos (ffmpeg; needs `brew install ffmpeg`)
#   dev-worker-sim    runs practice tickets (calls the language model; bounded concurrency)
#   dev-beat          the single scheduler that runs the recovery sweepers
#   dev-workers       all three, together (Ctrl-C stops them all)
# They use Celery's filesystem broker (backend/.celery-broker/), so no Redis is needed
# locally. Each recovers anything an earlier process left half-done when it starts.
# macOS only: a forked worker that first touches Apple's certificate store (the model client
# does) is killed by the Objective-C runtime ("Python quit unexpectedly"); this switch is the
# standard remedy. Linux (CI, Docker, production) has no such runtime and is unaffected.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY := YES
dev-worker-media: dev-db
	cd backend && uv run celery -A config worker -Q media -n media@%h -c $${MEDIA_WORKER_CONCURRENCY:-1} -l info

dev-worker-sim: dev-db
	cd backend && uv run celery -A config worker -Q sim -n sim@%h -c $${SIMBOT_WORKER_CONCURRENCY:-4} --max-tasks-per-child 200 --prefetch-multiplier 1 -l info

dev-beat: dev-db
	cd backend && uv run celery -A config beat -s .celery-broker/beat-schedule -l info

dev-workers: dev-db
	cd backend && (trap 'kill 0' INT TERM; \
	  uv run celery -A config worker -Q media -n media@%h -c $${MEDIA_WORKER_CONCURRENCY:-1} -l info & \
	  uv run celery -A config worker -Q sim -n sim@%h -c $${SIMBOT_WORKER_CONCURRENCY:-4} --max-tasks-per-child 200 --prefetch-multiplier 1 -l info & \
	  uv run celery -A config beat -s .celery-broker/beat-schedule -l info & \
	  wait)

# Kept for muscle memory: everything background work needs.
dev-worker: dev-workers

# 13 practice tickets at once while three videos convert, on real processes (docs/simbot.md).
# Needs Postgres (DATABASE_URL) and ffmpeg; takes about four minutes; prints the figures.
# Serves with gunicorn as shipped; LOAD_WEB=runserver uses Django's dev server instead.
load-test:
	cd backend && uv run pytest -m load -s tests/load

# Run in a second terminal alongside `make dev` — the SPA (:5173) proxies
# /api requests to Django (:8000), so both need to be up at once.
frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm run test -- --run

lint:
	cd backend && uv run ruff check . && uv run mypy .

# Stubs — real implementations land in M6 (Hardening + pilot).
backup:
	@echo "backup: not implemented until M6 — see docs/architecture.md §13"

restore-drill:
	@echo "restore-drill: not implemented until M6 — see docs/architecture.md §13"
