"""
Shared Django settings for the Hevo Support Training Platform.
Environment-specific settings (dev/prod/test) import * from here.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-me-in-prod")
DEBUG = env.bool("DEBUG", default=False)

# Lets a signed-in user wipe their *own* attempts at a scored activity so a
# quiz can be re-taken. It defeats the attempt limit, so it is off unless
# switched on (dev.py does); real use arrives as a trainer screen.
ALLOW_ATTEMPT_RESET = env.bool("ALLOW_ATTEMPT_RESET", default=False)

# Django Admin is now restricted emergency access (superusers only, under
# /django-admin/). It stays mounted until the Admin Console has full parity
# (docs/admin-parity-inventory.md); only then is this switched off in production.
ENABLE_DJANGO_ADMIN = env.bool("ENABLE_DJANGO_ADMIN", default=True)

# When on, anyone whose account is flagged "must change password" (a new user, or
# one whose password an admin reset) is sent to the change screen before they can
# use anything else. Off by default while accounts are being set up and tested;
# the flag is still recorded and the voluntary "Change password" screen still works.
ENFORCE_PASSWORD_CHANGE = env.bool("ENFORCE_PASSWORD_CHANGE", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "adminsortable2",
    "django_json_widget",
    "axes",
    # local apps — only accounts and catalog are real in M1
    "apps.accounts",
    "apps.catalog",
    "apps.progress",
    "apps.audit",
    "apps.console",
    "apps.media_pipeline",
    "apps.bot_sim",
    "apps.manual_sim",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://hevo:hevo@localhost:5432/hevo_training",
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Argon2 first so it is used for all new/changed passwords; the rest stay
# for verifying any pre-existing hashes (there are none yet, but this is
# the standard Django ordering).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-axes: lockout after 5 failures / 15 min, per §11 of the architecture doc.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # hours
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
# Keep a durable record of failed sign-ins (and which ones caused a lockout),
# not just the live counter that is cleared on success or unlock. This is what
# the Admin Console's "Failed attempts" screen reads.
AXES_ENABLE_ACCESS_FAILURE_LOG = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
# Uploaded videos live here. It is deliberately NOT mapped to a URL anywhere:
# files are only ever reached through the authorised streaming views.
MEDIA_ROOT = env.path("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Session cookies, not JWTs, per §11 — same-origin SPA, no cross-domain requirement.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # A player sends a heartbeat every ~15 s (plus a few on pause/seek/leave).
    "DEFAULT_THROTTLE_RATES": {
        "video_watch": "40/min",
        "sim_start": "10/min",
        "sim_reply": "20/min",
        "sim_poll": "120/min",
        "manual_sim_submit": "20/hour",
    },
}

# Redis is provisioned in Compose from M1 onward (M2 needs it immediately for
# Celery/sessions-at-scale), but nothing reads/writes it yet in M1.
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# --------------------------------------------------------------------- media
# Video uploads, the background transcode, and the limits around it
# (docs/media-pipeline.md). Sizes are in MB so they read the way people say them.
MEDIA_MAX_UPLOAD_MB = env.float("MEDIA_MAX_UPLOAD_MB", default=1024)
MEDIA_MAX_DURATION_SECONDS = env.int("MEDIA_MAX_DURATION_SECONDS", default=7200)
MEDIA_MAX_PIXELS = env.int("MEDIA_MAX_PIXELS", default=3840 * 2160)
MEDIA_MAX_OUTPUT_MB = env.float("MEDIA_MAX_OUTPUT_MB", default=2048)
# Refuse an upload (and stop a transcode) when less than this would remain free.
MEDIA_MIN_FREE_MB = env.float("MEDIA_MIN_FREE_MB", default=2048)
MEDIA_ALLOWED_EXTENSIONS = ("mp4", "mov", "m4v", "webm", "mkv")
# The original is deleted only after the transcoded file is verified and `ready`
# is committed. Set true to keep every original.
MEDIA_KEEP_ORIGINALS = env.bool("MEDIA_KEEP_ORIGINALS", default=False)
MEDIA_MAX_ATTEMPTS = env.int("MEDIA_MAX_ATTEMPTS", default=3)
MEDIA_MAX_UNFINISHED_PER_USER = env.int("MEDIA_MAX_UNFINISHED_PER_USER", default=3)
# An asset waiting this long with no worker having picked it up is re-queued.
MEDIA_REQUEUE_AFTER_SECONDS = env.int("MEDIA_REQUEUE_AFTER_SECONDS", default=120)
# Extra time a worker's claim stays valid beyond the longest transcode allowed.
MEDIA_LEASE_SLACK_SECONDS = env.int("MEDIA_LEASE_SLACK_SECONDS", default=120)
# A temp folder must be at least this old before the sweeper may remove it.
MEDIA_DEBRIS_MIN_AGE_SECONDS = env.int("MEDIA_DEBRIS_MIN_AGE_SECONDS", default=60)
# Wait before a failed attempt is tried again: this × the attempt number.
MEDIA_RETRY_BACKOFF_SECONDS = env.int("MEDIA_RETRY_BACKOFF_SECONDS", default=30)
MEDIA_PROBE_TIMEOUT_SECONDS = env.int("MEDIA_PROBE_TIMEOUT_SECONDS", default=30)
MEDIA_TRANSCODE_TIMEOUT_SECONDS = env.int("MEDIA_TRANSCODE_TIMEOUT_SECONDS", default=3600)
# At most two transcodes at once, however high this is set (see docs).
MEDIA_WORKER_CONCURRENCY = min(env.int("MEDIA_WORKER_CONCURRENCY", default=1), 2)
FFMPEG_BIN = env("FFMPEG_BIN", default="ffmpeg")
# ffmpeg runs at lower CPU priority so a conversion never starves the web tier (0 = off).
MEDIA_FFMPEG_NICE = env.int("MEDIA_FFMPEG_NICE", default=10)
FFPROBE_BIN = env("FFPROBE_BIN", default="ffprobe")
# Set to an internal location prefix (e.g. "/protected-media/") to let nginx
# send the bytes via X-Accel-Redirect instead of Django. Empty = Django serves.
MEDIA_ACCEL_REDIRECT = env("MEDIA_ACCEL_REDIRECT", default="")

# -------------------------------------------------------------------- celery
# State lives in the database (MediaAsset), not in task results, so there is no
# result backend. Reliability does not depend on the broker either: a sweeper
# re-queues anything a lost message or a killed worker left behind.
#
# Docker/production: Redis (CELERY_BROKER_URL=redis://…). Local development has
# neither Redis nor Docker, so the default is Celery's filesystem transport — a
# development-only broker with no redelivery after a hard kill (the sweeper
# covers that). Its folder sits outside MEDIA_ROOT so it can never be served.
CELERY_BROKER_FOLDER = env.path("CELERY_BROKER_FOLDER", default=str(BASE_DIR / ".celery-broker"))
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="filesystem://")
CELERY_BROKER_TRANSPORT_OPTIONS: dict[str, object]
if CELERY_BROKER_URL.startswith("filesystem"):
    _broker = str(CELERY_BROKER_FOLDER)
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": f"{_broker}/queue",
        "data_folder_out": f"{_broker}/queue",
        "control_folder": f"{_broker}/control",
        "processed_folder": f"{_broker}/processed",
    }
    for _sub in ("queue", "control", "processed"):
        Path(f"{_broker}/{_sub}").mkdir(parents=True, exist_ok=True)
else:
    CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 2 * 3600}
CELERY_TASK_IGNORE_RESULT = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ROUTES = {
    "media_pipeline.*": {"queue": "media"},
    "bot_sim.*": {"queue": "sim"},
}
CELERY_TASK_DEFAULT_QUEUE = "media"
SIMBOT_TOPUP_HOUR = env.int("SIMBOT_TOPUP_HOUR", default=2)  # UTC (TIME_ZONE)
SIMBOT_TOPUP_MINUTE = env.int("SIMBOT_TOPUP_MINUTE", default=30)
CELERY_BEAT_SCHEDULE = {
    "media-recover": {"task": "media_pipeline.recover", "schedule": 300.0},
    "sim-recover": {"task": "bot_sim.recover", "schedule": 60.0},
    "sim-top-up": {
        "task": "bot_sim.top_up",
        "schedule": crontab(hour=SIMBOT_TOPUP_HOUR, minute=SIMBOT_TOPUP_MINUTE),
    },
}

# ------------------------------------------------------------------ simbot
# Practice tickets (docs/simbot.md). The engine (`simbot_engine/`) never reads
# settings; `apps/bot_sim` builds its config from these.
SIMBOT_ENABLED = env.bool("SIMBOT_ENABLED", default=True)
# "openai" (real), or "fake" (development/tests/load tests only — refused in prod).
SIMBOT_LLM = env("SIMBOT_LLM", default="openai")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
SIMBOT_MODEL = env("SIMBOT_MODEL", default="gpt-4o-mini")  # customer and scenarios
SIMBOT_EVAL_MODEL = env("SIMBOT_EVAL_MODEL", default="gpt-4o-mini")  # scoring and feedback
SIMBOT_MAX_EXCHANGES = env.int("SIMBOT_MAX_EXCHANGES", default=6)
SIMBOT_SESSION_CAP_MINUTES = env.int("SIMBOT_SESSION_CAP_MINUTES", default=90)
SIMBOT_MAX_REPLY_CHARS = 4000
# A worker's claim on a turn; and how often a failed step is tried again.
SIMBOT_LEASE_SECONDS = env.int("SIMBOT_LEASE_SECONDS", default=120)
SIMBOT_MAX_JOB_ATTEMPTS = env.int("SIMBOT_MAX_JOB_ATTEMPTS", default=4)
SIMBOT_RETRY_BACKOFF_SECONDS = env.int("SIMBOT_RETRY_BACKOFF_SECONDS", default=5)
# A finishing ticket whose result has been started this many times without ever finishing
# (a worker that keeps dying, a provider that never answers) is closed instead of left waiting.
SIMBOT_MAX_FINALIZE_CLAIMS = env.int("SIMBOT_MAX_FINALIZE_CLAIMS", default=12)
# One simulation worker *process* with this many children; hard-capped at 8.
SIMBOT_WORKER_CONCURRENCY = min(env.int("SIMBOT_WORKER_CONCURRENCY", default=4), 8)
# Provider limits and cost safeguards (size these to your OpenAI tier).
SIMBOT_LLM_RPM = env.int("SIMBOT_LLM_RPM", default=300)
SIMBOT_LLM_TPM = env.int("SIMBOT_LLM_TPM", default=150_000)
SIMBOT_LLM_MAX_WAIT_SECONDS = env.float("SIMBOT_LLM_MAX_WAIT_SECONDS", default=8.0)
SIMBOT_LLM_CALL_TIMEOUT = env.float("SIMBOT_LLM_CALL_TIMEOUT", default=30.0)
SIMBOT_LLM_CALL_ATTEMPTS = env.int("SIMBOT_LLM_CALL_ATTEMPTS", default=3)
SIMBOT_SESSION_TOKEN_BUDGET = env.int("SIMBOT_SESSION_TOKEN_BUDGET", default=60_000)
SIMBOT_DAILY_TOKEN_CAP = env.int("SIMBOT_DAILY_TOKEN_CAP", default=3_000_000)
SIMBOT_DAILY_SESSIONS_PER_USER = env.int("SIMBOT_DAILY_SESSIONS_PER_USER", default=12)
# How many questions a learner may skip per practice activity (duplicates, unclear ones).
SIMBOT_SKIPS_PER_ACTIVITY = env.int("SIMBOT_SKIPS_PER_ACTIVITY", default=5)
SIMBOT_BREAKER_FAILURES = env.int("SIMBOT_BREAKER_FAILURES", default=6)
SIMBOT_BREAKER_COOLDOWN_SECONDS = env.int("SIMBOT_BREAKER_COOLDOWN_SECONDS", default=60)
SIMBOT_TRANSCRIPT_RETENTION_DAYS = env.int("SIMBOT_TRANSCRIPT_RETENTION_DAYS", default=180)
# Only for the fake model: a JSON file the test harness edits to inject latency/faults.
SIMBOT_FAKE_CONTROL = env("SIMBOT_FAKE_CONTROL", default="")

# ------------------------------------------------------- Zendesk (read-only source)
# Past customer queries become practice scenarios (docs/simbot.md). Credentials live in the
# environment only. Importing is OFF until someone records the data-protection sign-off.
ZENDESK_SUBDOMAIN = env("ZENDESK_SUBDOMAIN", default="")
ZENDESK_EMAIL = env("ZENDESK_EMAIL", default="")
ZENDESK_API_TOKEN = env("ZENDESK_API_TOKEN", default="")
ZENDESK_FORM_NAMES = env.list("ZENDESK_FORM_NAMES", default=["Query", "Query_Old"])
# Tickets the old bot (or anyone) created through the API must never come back as "customers".
ZENDESK_EXCLUDE_REQUESTER_IDS = env.list("ZENDESK_EXCLUDE_REQUESTER_IDS", cast=int, default=[])
ZENDESK_EXCLUDE_GROUP_IDS = env.list("ZENDESK_EXCLUDE_GROUP_IDS", cast=int, default=[])
ZENDESK_EXCLUDE_TAGS = env.list("ZENDESK_EXCLUDE_TAGS", default=[])
ZENDESK_STAFF_DOMAINS = env.list("ZENDESK_STAFF_DOMAINS", default=[])
SIMBOT_ZENDESK_IMPORT_ENABLED = env.bool("SIMBOT_ZENDESK_IMPORT_ENABLED", default=False)
# Who approved sending scrubbed customer text to the model provider, when, and the reference.
SIMBOT_ZENDESK_SIGNOFF = env("SIMBOT_ZENDESK_SIGNOFF", default="")
# Master switch for approving imported scenarios automatically (strict checks still apply).
SIMBOT_AUTO_APPROVE = env.bool("SIMBOT_AUTO_APPROVE", default=True)
# Nightly top-up of the approved-question bank. The environment value is the master switch
# (false = never); the Console switch is off until an administrator turns it on.
SIMBOT_TOPUP_ENABLED = env.bool("SIMBOT_TOPUP_ENABLED", default=True)
SIMBOT_BANK_TARGET = env.int("SIMBOT_BANK_TARGET", default=30)  # approved questions wanted
SIMBOT_TOPUP_COUNT = env.int("SIMBOT_TOPUP_COUNT", default=20)  # tickets examined per night
SIMBOT_TOPUP_MAX_DRAFTS = env.int("SIMBOT_TOPUP_MAX_DRAFTS", default=25)  # waiting for review
SIMBOT_TOPUP_PAUSE_AFTER = env.int("SIMBOT_TOPUP_PAUSE_AFTER", default=3)  # empty nights in a row

# --------------------------------------------------------------- manual_sim
# Mentor-rated simulations (docs/manual-simulation.md). Everything a person decides here is a
# setting, not a constant: how long a mentor has, when an overdue review opens to others, and
# how much a learner may attach.
MANUAL_SIM_REVIEW_HOURS = env.int("MANUAL_SIM_REVIEW_HOURS", default=48)  # mentor's target
MANUAL_SIM_ESCALATION_GRACE_HOURS = env.int("MANUAL_SIM_ESCALATION_GRACE_HOURS", default=24)
# Unsuccessful reviews before a case is flagged for attention.
MANUAL_SIM_ATTENTION_AFTER = env.int("MANUAL_SIM_ATTENTION_AFTER", default=3)
MANUAL_SIM_EXTEND_MAX_DAYS = env.int("MANUAL_SIM_EXTEND_MAX_DAYS", default=14)  # per extension
MANUAL_SIM_CLAIM_MINUTES = env.int("MANUAL_SIM_CLAIM_MINUTES", default=120)  # a claim's lease
MANUAL_SIM_MAX_ANSWER_CHARS = env.int("MANUAL_SIM_MAX_ANSWER_CHARS", default=10_000)
MANUAL_SIM_MAX_LINKS = env.int("MANUAL_SIM_MAX_LINKS", default=5)
MANUAL_SIM_MAX_FILES = env.int("MANUAL_SIM_MAX_FILES", default=5)
MANUAL_SIM_MAX_FILE_MB = env.float("MANUAL_SIM_MAX_FILE_MB", default=10)
MANUAL_SIM_MAX_TOTAL_MB = env.float("MANUAL_SIM_MAX_TOTAL_MB", default=25)
# A decompression-bomb cap on image dimensions (width x height).
MANUAL_SIM_MAX_PIXELS = env.int("MANUAL_SIM_MAX_PIXELS", default=36_000_000)
