"""Refusals a learner or trainer can act on. Messages are plain sentences; nothing
from the model provider ever appears in them."""

from __future__ import annotations


class SimError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFound(SimError):
    status_code = 404


class Conflict(SimError):
    status_code = 409


class Unavailable(SimError):
    """Practice can't run right now (paused, not configured, no scenarios)."""

    status_code = 503


class TooMany(SimError):
    status_code = 429


class BadReply(SimError):
    status_code = 400


class NoScenarios(Conflict):
    pass
