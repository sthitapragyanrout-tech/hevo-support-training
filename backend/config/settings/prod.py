"""Production settings. Everything server-specific comes from the environment (see
.env.prod.example and DEPLOY.md); nothing here names a real host or holds a secret.

The app sits behind nginx, which terminates HTTPS and passes X-Forwarded-Proto.
"""

from .base import *  # noqa: F401,F403
from .base import env


class MisconfiguredError(RuntimeError):
    """A plain error (not ImproperlyConfigured, which manage.py hides) so the message shows."""


DEBUG = False

# A real key is required: refuse to start on the development fallback or a short one.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY or SECRET_KEY.startswith("django-insecure") or len(SECRET_KEY) < 40:
    raise MisconfiguredError(
        "Set DJANGO_SECRET_KEY to a long random value (see DEPLOY.md) before starting."
    )

# The site's own address(es), e.g. training.example.com. Required: Django refuses
# requests for any other host.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    raise MisconfiguredError("Set ALLOWED_HOSTS to the site's domain (see DEPLOY.md).")

# Full origins the browser uses, e.g. https://training.example.com. Defaults to https:// on
# each allowed host, which is right when the site is served over HTTPS on the normal port.
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=[f"https://{h}" for h in ALLOWED_HOSTS if h != "*"]
)

# --- HTTPS -------------------------------------------------------------------------------
# Set USE_HTTPS=false only for a first trial over plain http (e.g. by IP address before a
# certificate exists). Cookies are then not marked secure, so never leave it that way.
USE_HTTPS = env.bool("USE_HTTPS", default=True)
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# nginx redirects http → https itself; this is the backstop.
SECURE_SSL_REDIRECT = USE_HTTPS and env.bool("SECURE_SSL_REDIRECT", default=True)
# HSTS starts short; raise it (e.g. to 31536000) once HTTPS is known to work everywhere.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600) if USE_HTTPS else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# --- Things that must not be on for real learners -----------------------------------------
ALLOW_ATTEMPT_RESET = False
ENFORCE_PASSWORD_CHANGE = env.bool("ENFORCE_PASSWORD_CHANGE", default=True)

# The scripted model is for development and tests; it must never score real learners.
if SIMBOT_LLM == "fake":  # noqa: F405
    raise RuntimeError("SIMBOT_LLM=fake is not allowed in production.")

# --- Logs ----------------------------------------------------------------------------------
# Everything to stdout/stderr, where Docker (or journald) keeps and rotates it.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
