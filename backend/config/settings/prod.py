"""
Production settings stub. Real hardening (HSTS, CSP, secrets management,
nginx/gunicorn tuning per §11/§13 of docs/architecture.md) is M6 scope —
this file exists only so the settings-package shape is stable from M1 on.
"""

from .base import *  # noqa: F401,F403

DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
