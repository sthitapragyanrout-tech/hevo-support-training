"""
Settings for pytest. Defaults to a fast local SQLite DB so `pytest` works
without a running Postgres; CI sets DATABASE_URL to a real postgres service
container so the test suite also runs against the production engine there.
"""

import os

from .base import *  # noqa: F401,F403

DEBUG = False

if "DATABASE_URL" not in os.environ:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast for tests
AXES_ENABLED = False
