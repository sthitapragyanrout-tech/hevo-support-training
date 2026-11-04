"""
Production settings stub. Real hardening (HSTS, CSP, secrets management,
nginx/gunicorn tuning per §11/§13 of docs/architecture.md) is M6 scope —
this file exists only so the settings-package shape is stable from M1 on.
"""

from .base import *  # noqa: F401,F403

DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# The scripted model is for development and tests; it must never score real learners.
if SIMBOT_LLM == "fake":  # noqa: F405
    raise RuntimeError("SIMBOT_LLM=fake is not allowed in production.")
