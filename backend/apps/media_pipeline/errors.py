"""Failures with a sentence an author can act on and the HTTP status to match.
Nothing in `message` ever comes from ffmpeg or the file system."""

from __future__ import annotations


class MediaError(Exception):
    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class TooLarge(MediaError):
    status_code = 413


class NotAVideo(MediaError):
    status_code = 400


class LimitExceeded(MediaError):
    status_code = 400


class TooManyUnfinished(MediaError):
    status_code = 429


class NoSpace(MediaError):
    status_code = 503


class TransientError(Exception):
    """A processing problem that may well pass (disk full, timeout, a killed
    process): the asset is queued again until the attempt limit is reached."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PermanentError(Exception):
    """The file itself can't be turned into a playable video; retrying the same
    file will not help."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
