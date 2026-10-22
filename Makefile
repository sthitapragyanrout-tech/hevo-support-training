.PHONY: up down migrate seed test lint shell backup restore-drill dev dev-db dev-migrate dev-seed dev-shell frontend

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
