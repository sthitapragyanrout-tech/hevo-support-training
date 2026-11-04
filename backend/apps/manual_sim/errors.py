"""Refusals a learner, mentor or trainer can act on: plain sentences, each with the HTTP status
it should be shown with."""

from __future__ import annotations


class SimError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class BadInput(SimError):
    status_code = 400


class Forbidden(SimError):
    status_code = 403


class NotFound(SimError):
    status_code = 404


class Conflict(SimError):
    status_code = 409


class TooLarge(SimError):
    status_code = 413
