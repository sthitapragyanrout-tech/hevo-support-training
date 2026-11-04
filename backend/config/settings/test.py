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

# Media: a throwaway directory, and tasks run inline unless a test starts a real
# worker (which sets CELERY_TASK_ALWAYS_EAGER=false and shares MEDIA_ROOT/broker).
import tempfile  # noqa: E402

if "MEDIA_ROOT" not in os.environ:
    MEDIA_ROOT = tempfile.mkdtemp(prefix="hevo-test-media-")
if "CELERY_BROKER_FOLDER" not in os.environ:
    CELERY_BROKER_FOLDER = tempfile.mkdtemp(prefix="hevo-test-broker-")
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": f"{CELERY_BROKER_FOLDER}/queue",
        "data_folder_out": f"{CELERY_BROKER_FOLDER}/queue",
        "control_folder": f"{CELERY_BROKER_FOLDER}/control",
        "processed_folder": f"{CELERY_BROKER_FOLDER}/processed",
    }
    for _sub in ("queue", "control", "processed"):
        os.makedirs(f"{CELERY_BROKER_FOLDER}/{_sub}", exist_ok=True)
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "true").lower() != "false"
CELERY_TASK_EAGER_PROPAGATES = True
MEDIA_MIN_FREE_MB = 1  # tests must not depend on how full this machine's disk is

# Practice tickets run against the scripted model, inline, with generous limits.
SIMBOT_LLM = "fake"
SIMBOT_ENABLED = True
SIMBOT_RETRY_BACKOFF_SECONDS = 0
