"""
Shared Django settings for the Hevo Support Training Platform.
Environment-specific settings (dev/prod/test) import * from here.
"""

from pathlib import Path

import environ

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
MEDIA_ROOT = BASE_DIR / "media"

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
}

# Redis is provisioned in Compose from M1 onward (M2 needs it immediately for
# Celery/sessions-at-scale), but nothing reads/writes it yet in M1.
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
